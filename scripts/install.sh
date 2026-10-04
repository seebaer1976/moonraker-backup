#!/usr/bin/env bash
# Install / reinstall moonraker-backup into an existing Moonraker setup
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPONENT_SRC="${ROOT_DIR}/component/backup.py"

MOONRAKER_DIR="${MOONRAKER_DIR:-${HOME}/moonraker}"
PRINTER_DATA="${PRINTER_DATA:-${HOME}/printer_data}"
CONFIG_DIR="${PRINTER_DATA}/config"
MOONRAKER_CONF="${CONFIG_DIR}/moonraker.conf"
BACKUP_DIR="${PRINTER_DATA}/backups"
COMPONENTS_DIR="${MOONRAKER_DIR}/moonraker/components"

echo "==> moonraker-backup installer"
echo "    repo:       ${ROOT_DIR}"
echo "    moonraker:  ${MOONRAKER_DIR}"
echo "    data:       ${PRINTER_DATA}"

if [[ ! -f "${COMPONENT_SRC}" ]]; then
  echo "ERROR: component not found: ${COMPONENT_SRC}"
  exit 1
fi

if [[ ! -d "${COMPONENTS_DIR}" ]]; then
  echo "ERROR: Moonraker components dir not found: ${COMPONENTS_DIR}"
  echo "Set MOONRAKER_DIR if Moonraker lives elsewhere."
  exit 1
fi

mkdir -p "${BACKUP_DIR}"
cp -f "${COMPONENT_SRC}" "${COMPONENTS_DIR}/backup.py"
echo "OK  component -> ${COMPONENTS_DIR}/backup.py"

if [[ -f "${MOONRAKER_CONF}" ]]; then
  if ! grep -qE '^\[backup\]' "${MOONRAKER_CONF}"; then
    cat >> "${MOONRAKER_CONF}" <<'ECONF'

# ----- moonraker-backup -----
[backup]
# source_path: ~/printer_data/config
# storage_path: ~/printer_data/backups
# max_backups: 20
# block_during_print: True
# backup_before_update: True
ECONF
    echo "OK  appended [backup] to ${MOONRAKER_CONF}"
  else
    echo "OK  [backup] already in ${MOONRAKER_CONF}"
  fi
else
  echo "WARN ${MOONRAKER_CONF} missing – add [backup] manually (see moonraker-example.conf)"
fi

echo
echo "Tipp: Update-Manager siehe moonraker-example.conf (origin auf dein GitHub setzen)."
echo
echo "Fertig. Moonraker neu starten:"
echo "  sudo systemctl restart moonraker"
echo
echo "Status testen:"
echo "  curl -s http://127.0.0.1:7125/machine/backup/status | head"
echo
echo "Optional Klipper:"
echo "  [include ${ROOT_DIR}/klipper_macro/backup.cfg]"
