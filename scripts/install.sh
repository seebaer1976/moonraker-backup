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
SETTINGS_FILE="${CONFIG_DIR}/moonraker-backup-settings.cfg"
BACKUP_DIR="${PRINTER_DATA}/backups"
COMPONENTS_DIR="${MOONRAKER_DIR}/moonraker/components"
GITHUB_ORIGIN="https://github.com/seebaer1976/moonraker-backup.git"

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

mkdir -p "${BACKUP_DIR}" "${CONFIG_DIR}"
cp -f "${COMPONENT_SRC}" "${COMPONENTS_DIR}/backup.py"
echo "OK  component -> ${COMPONENTS_DIR}/backup.py"

# Settings file (GUI / API writes here)
if [[ ! -f "${SETTINGS_FILE}" ]]; then
  cat > "${SETTINGS_FILE}" << "ESET"
# moonraker-backup settings – changeable via Web-UI / API
# Do not remove the [backup] header.
[backup]
# Standard: gesamtes printer_data/config
source_path: ~/printer_data/config
storage_path: ~/printer_data/backups
max_backups: 20
exclude: .git,*.pyc,__pycache__,.DS_Store
name_prefix: config-backup
block_during_print: True
backup_before_update: True
ESET
  echo "OK  created ${SETTINGS_FILE}"
else
  echo "OK  settings file exists: ${SETTINGS_FILE}"
fi

if [[ ! -f "${MOONRAKER_CONF}" ]]; then
  echo "WARN creating ${MOONRAKER_CONF}"
  touch "${MOONRAKER_CONF}"
fi

if ! grep -qE 'moonraker-backup-settings\.cfg' "${MOONRAKER_CONF}"; then
  printf '\n# ----- moonraker-backup (settings editable via UI) -----\n[include moonraker-backup-settings.cfg]\n' >> "${MOONRAKER_CONF}"
  echo "OK  added [include moonraker-backup-settings.cfg]"
else
  echo "OK  include for settings already present"
fi

if ! grep -qE '^\[update_manager moonraker-backup\]' "${MOONRAKER_CONF}"; then
  {
    echo ""
    echo "[update_manager moonraker-backup]"
    echo "type: git_repo"
    echo "path: ~/moonraker-backup"
    echo "origin: ${GITHUB_ORIGIN}"
    echo "primary_branch: main"
    echo "managed_services: moonraker"
    echo "install_script: scripts/install.sh"
  } >> "${MOONRAKER_CONF}"
  echo "OK  added [update_manager moonraker-backup]"
else
  echo "OK  [update_manager moonraker-backup] already present"
fi

echo
echo "Fertig. Moonraker neu starten:"
echo "  sudo systemctl restart moonraker"
echo
echo "Status testen:"
echo "  curl -s http://127.0.0.1:7125/machine/backup/status | head"
echo
echo "Optional Klipper:"
echo "  [include ${ROOT_DIR}/klipper_macro/backup.cfg]"
