# Moonraker Backup component
#
# Local zip backups of printer config (inspired by klipper-backup + timelapse API)
#
# Copyright (C) 2026
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from confighelper import ConfigHelper
    from websockets import WebRequest

COMPONENT_VERSION = "0.2.0"
DB_NAMESPACE = "backup"
# print_stats states that block create/restore
_PRINT_BLOCK_STATES = {"printing", "paused"}


class Backup:
    def __init__(self, config: ConfigHelper) -> None:
        self.server = config.get_server()
        self.confighelper = config
        self.eventloop = self.server.get_event_loop()
        self.database = self.server.lookup_component("database")

        app_args = self.server.get_app_args()
        self.data_path = Path(
            app_args.get("data_path", os.path.expanduser("~/printer_data"))
        )

        default_source = str(self.data_path / "config")
        default_storage = str(self.data_path / "backups")

        source_cfg = config.get("source_path", default_source)
        storage_cfg = config.get("storage_path", default_storage)

        self.source_path = Path(os.path.expanduser(source_cfg)).resolve()
        self.storage_path = Path(os.path.expanduser(storage_cfg)).resolve()
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.config: Dict[str, Any] = {
            "enabled": True,
            "source_path": str(self.source_path),
            "storage_path": str(self.storage_path),
            "max_backups": 20,
            "include_glob": "*",
            "exclude": ".git,*.pyc,__pycache__,.DS_Store",
            "name_prefix": "config-backup",
            # block create/restore while printing or paused
            "block_during_print": True,
            # auto zip before Moonraker Update Manager runs
            "backup_before_update": True,
        }

        dbconfig = self.database.get_item(DB_NAMESPACE, "config", {})
        if isinstance(dbconfig, asyncio.Future):
            dbconfig = dbconfig.result()
        if isinstance(dbconfig, dict):
            self.config.update(dbconfig)

        self._apply_conf_overrides()
        self._busy = False
        self._last_error: Optional[str] = None
        self._update_backup_done_for: Optional[Any] = None
        self._print_state: str = "standby"

        file_manager = self.server.lookup_component("file_manager")
        file_manager.register_directory(
            "backups", str(self.storage_path), full_access=True
        )

        self.server.register_notification("backup:backup_event")
        self.server.register_endpoint(
            "/machine/backup/status", ["GET"], self._handle_status
        )
        self.server.register_endpoint(
            "/machine/backup/list", ["GET"], self._handle_list
        )
        self.server.register_endpoint(
            "/machine/backup/create", ["POST"], self._handle_create
        )
        self.server.register_endpoint(
            "/machine/backup/delete", ["POST"], self._handle_delete
        )
        self.server.register_endpoint(
            "/machine/backup/restore", ["POST"], self._handle_restore
        )
        self.server.register_endpoint(
            "/machine/backup/settings", ["GET", "POST"], self._handle_settings
        )
        self.server.register_endpoint(
            "/machine/backup/download", ["GET"], self._handle_download
        )

        self.server.register_remote_method("backup_create", self._remote_create)

        # track print state
        self.server.register_event_handler(
            "server:status_update", self._handle_status_update
        )
        # best-effort: backup once when Update Manager starts an update
        self.server.register_event_handler(
            "update_manager:update_response", self._handle_update_response
        )

        logging.info(
            "backup: component loaded v%s source=%s storage=%s "
            "block_during_print=%s backup_before_update=%s",
            COMPONENT_VERSION,
            self.source_path,
            self.storage_path,
            self.config.get("block_during_print"),
            self.config.get("backup_before_update"),
        )

    def _handle_status_update(self, status: Dict[str, Any]) -> None:
        pstats = status.get("print_stats")
        if isinstance(pstats, dict) and "state" in pstats:
            self._print_state = str(pstats["state"]).lower()

    def _is_print_blocking(self) -> bool:
        if not self.config.get("block_during_print", True):
            return False
        return self._print_state in _PRINT_BLOCK_STATES

    async def _assert_not_printing(self, action: str) -> None:
        if self._is_print_blocking():
            raise self.server.error(
                f"Cannot {action} while printer is {self._print_state}",
                409,
            )

    async def _handle_update_response(self, notification: Dict[str, Any]) -> None:
        """When Update Manager starts any update, create one config backup."""
        if not self.config.get("enabled", True):
            return
        if not self.config.get("backup_before_update", True):
            return
        if notification.get("complete"):
            return
        proc_id = notification.get("proc_id")
        if proc_id is None:
            return
        if self._update_backup_done_for == proc_id:
            return
        if self._busy:
            return
        if self._is_print_blocking():
            logging.info(
                "backup: skip pre-update backup (printer %s)", self._print_state
            )
            return

        self._update_backup_done_for = proc_id
        app = notification.get("application") or "update"
        note = f"auto-before-update:{app}"
        self._busy = True
        try:
            result = await self.eventloop.run_in_thread(
                self._create_backup_sync, note
            )
            await self.server.send_event(
                "backup:backup_event",
                {"action": "created", "backup": result, "trigger": "update_manager"},
            )
            logging.info(
                "backup: pre-update backup ok %s (%s)",
                result.get("filename"),
                app,
            )
        except Exception:
            logging.exception("backup: pre-update backup failed")
            self._update_backup_done_for = None
        finally:
            self._busy = False

    def _apply_conf_overrides(self) -> None:
        blocked: List[str] = []
        mapping = {
            "enabled": ("getboolean", bool),
            "source_path": ("get", str),
            "storage_path": ("get", str),
            "max_backups": ("getint", int),
            "include_glob": ("get", str),
            "exclude": ("get", str),
            "name_prefix": ("get", str),
            "block_during_print": ("getboolean", bool),
            "backup_before_update": ("getboolean", bool),
        }
        for key, (method, _typ) in mapping.items():
            if self.confighelper.has_option(key):
                getter = getattr(self.confighelper, method)
                self.config[key] = getter(key)
                blocked.append(key)
                if key == "source_path":
                    self.source_path = Path(
                        os.path.expanduser(self.config[key])
                    ).resolve()
                if key == "storage_path":
                    self.storage_path = Path(
                        os.path.expanduser(self.config[key])
                    ).resolve()
                    self.storage_path.mkdir(parents=True, exist_ok=True)
        self.config["blockedsettings"] = blocked

    def _exclude_list(self) -> List[str]:
        raw = self.config.get("exclude") or ""
        return [p.strip() for p in str(raw).split(",") if p.strip()]

    def _should_exclude(self, rel: str) -> bool:
        name = os.path.basename(rel)
        for pattern in self._exclude_list():
            if pattern.startswith("*") and name.endswith(pattern[1:]):
                return True
            if pattern == name or pattern == rel:
                return True
            if pattern in rel.split(os.sep):
                return True
        return False

    def _list_backups_sync(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        if not self.storage_path.is_dir():
            return items
        for path in sorted(self.storage_path.glob("*.zip"), reverse=True):
            try:
                st = path.stat()
                meta_path = path.with_suffix(".json")
                meta: Dict[str, Any] = {}
                if meta_path.is_file():
                    with open(meta_path, "r", encoding="utf-8") as fh:
                        meta = json.load(fh)
                items.append(
                    {
                        "filename": path.name,
                        "path": str(path),
                        "size": st.st_size,
                        "size_human": _human_size(st.st_size),
                        "mtime": st.st_mtime,
                        "mtime_iso": datetime.fromtimestamp(st.st_mtime).isoformat(
                            timespec="seconds"
                        ),
                        "note": meta.get("note", ""),
                        "source_path": meta.get("source_path", ""),
                        "file_count": meta.get("file_count", 0),
                    }
                )
            except OSError as exc:
                logging.warning("backup: skip %s: %s", path, exc)
        return items

    def _prune_old_sync(self) -> None:
        max_n = int(self.config.get("max_backups") or 0)
        if max_n <= 0:
            return
        zips = sorted(
            self.storage_path.glob("*.zip"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in zips[max_n:]:
            try:
                old.unlink(missing_ok=True)
                old.with_suffix(".json").unlink(missing_ok=True)
                logging.info("backup: pruned %s", old.name)
            except OSError as exc:
                logging.warning("backup: prune failed %s: %s", old, exc)

    def _create_backup_sync(self, note: str = "") -> Dict[str, Any]:
        if not self.source_path.is_dir():
            raise self.server.error(
                f"Source path not found: {self.source_path}", 404
            )

        prefix = re.sub(
            r"[^\w\-.]+", "_", str(self.config.get("name_prefix") or "config-backup")
        )
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{stamp}.zip"
        zip_path = self.storage_path / filename
        meta_path = zip_path.with_suffix(".json")

        file_count = 0
        with zipfile.ZipFile(
            zip_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as zf:
            for root, dirs, files in os.walk(self.source_path):
                rel_root = os.path.relpath(root, self.source_path)
                dirs[:] = [
                    d
                    for d in dirs
                    if not self._should_exclude(
                        d if rel_root == "." else os.path.join(rel_root, d)
                    )
                ]
                for name in files:
                    full = os.path.join(root, name)
                    rel = name if rel_root == "." else os.path.join(rel_root, name)
                    if self._should_exclude(rel):
                        continue
                    try:
                        zf.write(full, arcname=rel)
                        file_count += 1
                    except OSError as exc:
                        logging.warning("backup: skip file %s: %s", full, exc)

        meta = {
            "filename": filename,
            "created": datetime.now().isoformat(timespec="seconds"),
            "note": note or "",
            "source_path": str(self.source_path),
            "file_count": file_count,
            "component_version": COMPONENT_VERSION,
        }
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)

        self._prune_old_sync()
        st = zip_path.stat()
        result = {
            "filename": filename,
            "path": str(zip_path),
            "size": st.st_size,
            "size_human": _human_size(st.st_size),
            "file_count": file_count,
            "mtime_iso": meta["created"],
            "note": note or "",
        }
        return result

    def _restore_backup_sync(self, filename: str) -> Dict[str, Any]:
        safe = os.path.basename(filename)
        if not safe.endswith(".zip") or ".." in safe:
            raise self.server.error("Invalid backup filename", 400)
        zip_path = self.storage_path / safe
        if not zip_path.is_file():
            raise self.server.error(f"Backup not found: {safe}", 404)

        # Safety snapshot of current config before restore
        safety_note = f"auto-before-restore-{safe}"
        try:
            safety = self._create_backup_sync(note=safety_note)
        except Exception as exc:
            logging.warning("backup: safety snapshot failed: %s", exc)
            safety = None

        restored = 0
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                name = info.filename
                if name.endswith("/") or ".." in name.split("/"):
                    continue
                target = (self.source_path / name).resolve()
                if not str(target).startswith(str(self.source_path)):
                    logging.warning("backup: refuse path escape %s", name)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                restored += 1

        return {
            "restored_files": restored,
            "from_backup": safe,
            "target": str(self.source_path),
            "safety_backup": safety,
        }

    async def _handle_status(self, webrequest: WebRequest) -> Dict[str, Any]:
        backups = await self.eventloop.run_in_thread(self._list_backups_sync)
        last = backups[0] if backups else None
        return {
            "version": COMPONENT_VERSION,
            "enabled": bool(self.config.get("enabled", True)),
            "busy": self._busy,
            "last_error": self._last_error,
            "print_state": self._print_state,
            "print_blocked": self._is_print_blocking(),
            "source_path": str(self.source_path),
            "storage_path": str(self.storage_path),
            "backup_count": len(backups),
            "last_backup": last,
            "settings": {
                k: v
                for k, v in self.config.items()
                if k != "blockedsettings"
            },
            "blockedsettings": self.config.get("blockedsettings", []),
        }

    async def _handle_list(self, webrequest: WebRequest) -> Dict[str, Any]:
        backups = await self.eventloop.run_in_thread(self._list_backups_sync)
        return {"backups": backups}

    async def _handle_create(self, webrequest: WebRequest) -> Dict[str, Any]:
        if not self.config.get("enabled", True):
            raise self.server.error("Backup component is disabled", 400)
        await self._assert_not_printing("create a backup")
        if self._busy:
            raise self.server.error("Backup operation already running", 409)
        note = webrequest.get_str("note", "")
        self._busy = True
        self._last_error = None
        try:
            result = await self.eventloop.run_in_thread(
                self._create_backup_sync, note
            )
            await self.server.send_event(
                "backup:backup_event", {"action": "created", "backup": result}
            )
            return {"status": "ok", "backup": result}
        except self.server.error:
            raise
        except Exception as exc:
            self._last_error = str(exc)
            logging.exception("backup: create failed")
            raise self.server.error(f"Backup failed: {exc}", 500) from exc
        finally:
            self._busy = False

    async def _handle_delete(self, webrequest: WebRequest) -> Dict[str, Any]:
        filename = webrequest.get_str("filename")
        safe = os.path.basename(filename)
        path = self.storage_path / safe
        if not path.is_file():
            raise self.server.error(f"Backup not found: {safe}", 404)

        def _delete() -> None:
            path.unlink(missing_ok=True)
            path.with_suffix(".json").unlink(missing_ok=True)

        await self.eventloop.run_in_thread(_delete)
        await self.server.send_event(
            "backup:backup_event", {"action": "deleted", "filename": safe}
        )
        return {"status": "ok", "deleted": safe}

    async def _handle_restore(self, webrequest: WebRequest) -> Dict[str, Any]:
        await self._assert_not_printing("restore a backup")
        if self._busy:
            raise self.server.error("Backup operation already running", 409)
        filename = webrequest.get_str("filename")
        self._busy = True
        self._last_error = None
        try:
            result = await self.eventloop.run_in_thread(
                self._restore_backup_sync, filename
            )
            await self.server.send_event(
                "backup:backup_event", {"action": "restored", "result": result}
            )
            return {"status": "ok", "result": result}
        except self.server.error:
            raise
        except Exception as exc:
            self._last_error = str(exc)
            logging.exception("backup: restore failed")
            raise self.server.error(f"Restore failed: {exc}", 500) from exc
        finally:
            self._busy = False

    async def _handle_settings(self, webrequest: WebRequest) -> Dict[str, Any]:
        action = webrequest.get_action()
        if action == "POST":
            args = webrequest.get_args()
            blocked = set(self.config.get("blockedsettings") or [])
            for key, value in args.items():
                if key in blocked or key == "blockedsettings":
                    continue
                if key not in self.config:
                    continue
                cur = self.config[key]
                if isinstance(cur, bool):
                    self.config[key] = webrequest.get_boolean(key)
                elif isinstance(cur, int):
                    self.config[key] = webrequest.get_int(key)
                elif isinstance(cur, float):
                    self.config[key] = webrequest.get_float(key)
                else:
                    self.config[key] = webrequest.get_str(key)
                self.database.insert_item(
                    DB_NAMESPACE, f"config.{key}", self.config[key]
                )
            if "source_path" in args and "source_path" not in blocked:
                self.source_path = Path(
                    os.path.expanduser(self.config["source_path"])
                ).resolve()
            if "storage_path" in args and "storage_path" not in blocked:
                self.storage_path = Path(
                    os.path.expanduser(self.config["storage_path"])
                ).resolve()
                self.storage_path.mkdir(parents=True, exist_ok=True)
        return {
            "settings": {
                k: v
                for k, v in self.config.items()
                if k != "blockedsettings"
            },
            "blockedsettings": self.config.get("blockedsettings", []),
        }

    async def _handle_download(self, webrequest: WebRequest) -> Dict[str, Any]:
        """Return path info; actual download via Moonraker file_manager /server/files/backups/"""
        filename = webrequest.get_str("filename")
        safe = os.path.basename(filename)
        path = self.storage_path / safe
        if not path.is_file():
            raise self.server.error(f"Backup not found: {safe}", 404)
        return {
            "filename": safe,
            "download_url": f"/server/files/backups/{safe}",
            "size": path.stat().st_size,
            "size_human": _human_size(path.stat().st_size),
        }

    async def _remote_create(self, note: str = "") -> None:
        if self._busy or not self.config.get("enabled", True):
            return
        if self._is_print_blocking():
            logging.info(
                "backup: remote create blocked (printer %s)", self._print_state
            )
            return
        self._busy = True
        try:
            result = await self.eventloop.run_in_thread(
                self._create_backup_sync, note
            )
            await self.server.send_event(
                "backup:backup_event", {"action": "created", "backup": result}
            )
            logging.info("backup: remote create ok %s", result.get("filename"))
        except Exception:
            logging.exception("backup: remote create failed")
        finally:
            self._busy = False


def _human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"


def load_component(config: ConfigHelper) -> Backup:
    return Backup(config)
