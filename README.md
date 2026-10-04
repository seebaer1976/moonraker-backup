# moonraker-backup

Moonraker component for **local ZIP backups** of the Klipper config directory (`printer_data/config/`).

Inspired by [Klipper-Backup](https://github.com/Staubgeborener/Klipper-Backup) and the API pattern of [moonraker-timelapse](https://github.com/mainsail-crew/moonraker-timelapse).

Deutsch siehe Abschnitte unten – die Befehle sind universell.

## Features

| Feature | Description |
|--------|-------------|
| Manual backup | ZIP of config via API / macro / web UI |
| List | Timestamp, size, file count |
| Download | Via Moonraker file API |
| Restore | Creates a safety backup first |
| Print lock | No create/restore while `printing` or `paused` |
| Auto before update | One ZIP when the Update Manager starts an update |
| Settings API | GET/POST `/machine/backup/settings` (timelapse-style) |

> **Mainsail note:** A tab under the gear icon (⚙) requires upstream Mainsail support (like timelapse). This project provides the Moonraker API and a standalone UI at `ui/index.html`.

## Requirements

- Klipper + Moonraker (e.g. MainsailOS)
- Write access to `~/moonraker` and `~/printer_data`

## Installation

```bash
cd ~
git clone https://github.com/seebaer1976/moonraker-backup.git
cd ~/moonraker-backup
chmod +x scripts/install.sh
./scripts/install.sh
sudo systemctl restart moonraker
```

The install script will:

1. Copy `component/backup.py` into `~/moonraker/moonraker/components/backup.py`
2. Create `~/printer_data/config/moonraker-backup-settings.cfg` (if missing)
3. Add `[include moonraker-backup-settings.cfg]` to `moonraker.conf` (if missing)
4. Add the `[update_manager moonraker-backup]` block (if missing)
5. Create `~/printer_data/backups/`

### Moonraker Update Manager

Usually added automatically by `install.sh`. Manual entry for `moonraker.conf`:

```ini
[update_manager moonraker-backup]
type: git_repo
path: ~/moonraker-backup
origin: https://github.com/seebaer1976/moonraker-backup.git
primary_branch: main
managed_services: moonraker
install_script: scripts/install.sh
```

Restart Moonraker afterwards. The component should appear under **Machine → Update** in Mainsail/Fluidd.

### Settings file

Path: `~/printer_data/config/moonraker-backup-settings.cfg`

```ini
[backup]
source_path: ~/printer_data/config
storage_path: ~/printer_data/backups
max_backups: 20
exclude: .git,*.pyc,__pycache__,.DS_Store
name_prefix: config-backup
block_during_print: True
backup_before_update: True
```

Changes made via the **web UI or API** are written back to this file (and stored in the Moonraker database). They survive a Moonraker restart.

`moonraker.conf` only needs:

```ini
[include moonraker-backup-settings.cfg]
```

## Optional Klipper macro

In `printer.cfg`:

```ini
[include ~/moonraker-backup/klipper_macro/backup.cfg]
```

Or:

```ini
[gcode_macro BACKUP_CONFIG]
description: Create a ZIP backup of the config via Moonraker
gcode:
    {action_call_remote_method("backup_create", note="from-macro")}
```

## Web UI

Open in a browser:

```text
file:///home/pi/moonraker-backup/ui/index.html
```

(or copy/serve `ui/index.html`). Set the Moonraker base URL, e.g. `http://printer.local:7125`.

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/machine/backup/status` | Status, last backup, settings |
| GET | `/machine/backup/list` | All backups |
| POST | `/machine/backup/create` | Create backup (`note` optional) |
| POST | `/machine/backup/delete` | `filename=...` |
| POST | `/machine/backup/restore` | `filename=...` |
| GET/POST | `/machine/backup/settings` | Read/write settings |
| GET | `/server/files/backups/<file.zip>` | Download |

### Examples

```bash
curl -s http://127.0.0.1:7125/machine/backup/status

curl -X POST http://127.0.0.1:7125/machine/backup/create -d "note=before-change"

curl -s http://127.0.0.1:7125/machine/backup/list

curl -OJ http://127.0.0.1:7125/server/files/backups/config-backup_YYYYMMDD_HHMMSS.zip
```

## Behaviour

### During a print

With `block_during_print: True` (default):

- **Create** and **restore** are rejected while the printer is `printing` or `paused` (HTTP 409)

### Before software updates

With `backup_before_update: True` (default):

- When the Update Manager starts an update (Klipper, Moonraker, clients, …), **one** config ZIP is created
- Note example: `auto-before-update:klipper`

Moonraker has no official pre-update hook; this uses the `update_manager:update_response` event (best-effort).

### Restore

A safety backup is created before files under `source_path` are overwritten.  
Run a config check / `FIRMWARE_RESTART` if needed afterwards.

## Uninstall

```bash
rm -f ~/moonraker/moonraker/components/backup.py
# Remove [include moonraker-backup-settings.cfg] and
# [update_manager moonraker-backup] from moonraker.conf
sudo systemctl restart moonraker
```

ZIP files under `~/printer_data/backups/` are left in place.

## Project layout

```text
moonraker-backup/
├── README.md
├── LICENSE
├── .gitignore
├── moonraker-example.conf
├── component/backup.py
├── scripts/install.sh
├── klipper_macro/backup.cfg
└── ui/index.html
```

## License

GNU GPLv3 – see [LICENSE](LICENSE).

## Credits

- [Moonraker](https://github.com/Arksine/moonraker)
- [moonraker-timelapse](https://github.com/mainsail-crew/moonraker-timelapse)
- [Klipper-Backup](https://github.com/Staubgeborener/Klipper-Backup)
