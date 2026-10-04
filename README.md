# moonraker-backup

Moonraker-Komponente für **lokale ZIP-Backups** deiner Klipper-Config (`printer_data/config/`).

Inspiriert von [Klipper-Backup](https://github.com/Staubgeborener/Klipper-Backup) und dem API-Muster von [moonraker-timelapse](https://github.com/mainsail-crew/moonraker-timelapse).

## Features

| Feature | Beschreibung |
|--------|----------------|
| Manuelles Backup | ZIP der Config per API / Macro / Web-UI |
| Liste | Zeitpunkt, Größe, Dateianzahl |
| Download | Über Moonraker File-API |
| Restore | Mit automatischem Safety-Backup vorher |
| Druck-Sperre | Kein Create/Restore bei `printing` / `paused` |
| Auto vor Update | Ein ZIP, sobald der Update Manager ein Update startet |
| Settings-API | Wie Timelapse: GET/POST `/machine/backup/settings` |

> **Hinweis Mainsail:** Einen Tab unter den Zahnrädern (⚙) kann nur Mainsail selbst einbauen (wie bei Timelapse). Dieses Repo liefert die Moonraker-API und eine eigene Web-UI unter `ui/index.html`.

## Voraussetzungen

- Klipper + Moonraker (z. B. MainsailOS)
- Schreibrechte auf `~/moonraker` und `~/printer_data`

## Installation

```bash
cd ~
git clone https://github.com/DEIN_USER/moonraker-backup.git
cd ~/moonraker-backup
chmod +x scripts/install.sh
./scripts/install.sh
sudo systemctl restart moonraker
```

Das Install-Skript:

1. kopiert `component/backup.py` nach `~/moonraker/moonraker/components/backup.py`
2. legt `[backup]` in `moonraker.conf` an (falls fehlend)
3. erzeugt `~/printer_data/backups/`

### Moonraker Update Manager (empfohlen)

In `~/printer_data/config/moonraker.conf` eintragen:

```ini
[update_manager moonraker-backup]
type: git_repo
path: ~/moonraker-backup
origin: https://github.com/DEIN_USER/moonraker-backup.git
primary_branch: main
managed_services: moonraker
install_script: scripts/install.sh
```

`DEIN_USER` und ggf. `primary_branch` an dein Repo anpassen.  
Danach Moonraker neu starten – das Plugin erscheint unter **Maschine → Update**.

### Abschnitt `[backup]` (optional)

```ini
[backup]
# Standard: gesamtes printer_data/config
# source_path: ~/printer_data/config
# storage_path: ~/printer_data/backups
# max_backups: 20
# exclude: .git,*.pyc,__pycache__,.DS_Store
# name_prefix: config-backup
# block_during_print: True
# backup_before_update: True
```

Werte, die hier gesetzt sind, sind in der UI/API **nicht änderbar** (wie bei Timelapse `blockedsettings`).

## Klipper-Macro (optional)

In `printer.cfg`:

```ini
[include ~/moonraker-backup/klipper_macro/backup.cfg]
```

Oder manuell:

```ini
[gcode_macro BACKUP_CONFIG]
description: ZIP-Backup der Config über Moonraker
gcode:
    {action_call_remote_method("backup_create", note="from-macro")}
```

## Web-UI

Datei im Browser öffnen:

```text
~/moonraker-backup/ui/index.html
```

Moonraker-URL eintragen, z. B. `http://172.16.x.x:7125` oder `http://ender3.local:7125`.

## API-Übersicht

| Methode | Endpoint | Beschreibung |
|---------|----------|--------------|
| GET | `/machine/backup/status` | Status, letztes Backup, Settings |
| GET | `/machine/backup/list` | Alle Backups |
| POST | `/machine/backup/create` | Backup (`note` optional) |
| POST | `/machine/backup/delete` | `filename=...` |
| POST | `/machine/backup/restore` | `filename=...` |
| GET/POST | `/machine/backup/settings` | Settings lesen/schreiben |
| GET | `/server/files/backups/<datei.zip>` | Download |

### Beispiele

```bash
# Status
curl http://127.0.0.1:7125/machine/backup/status

# Backup erstellen
curl -X POST http://127.0.0.1:7125/machine/backup/create -d "note=vor-test"

# Liste
curl http://127.0.0.1:7125/machine/backup/list

# Download
curl -OJ http://127.0.0.1:7125/server/files/backups/config-backup_YYYYMMDD_HHMMSS.zip
```

## Verhalten

### Während eines Drucks

Wenn `block_during_print: True` (Standard):

- **Create** und **Restore** sind gesperrt, solange der Drucker `printing` oder `paused` ist
- Antwort: HTTP 409 mit Hinweis

### Vor Updates (Update Manager)

Wenn `backup_before_update: True` (Standard):

- Beim Start eines Updates über Mainsail/Fluidd (Klipper, Moonraker, Clients, …) wird **ein** Config-ZIP angelegt
- Notiz z. B. `auto-before-update:klipper`

Moonraker bietet keinen offiziellen Pre-Update-Hook; das Plugin nutzt das Event `update_manager:update_response` (best-effort).

### Restore

Vor dem Überschreiben der Config wird automatisch ein Safety-Backup erzeugt.  
Danach ggf. **FIRMWARE_RESTART** / Config prüfen.

## Deinstallation

```bash
rm -f ~/moonraker/moonraker/components/backup.py
# [backup] und [update_manager moonraker-backup] aus moonraker.conf entfernen
sudo systemctl restart moonraker
```

Backups unter `~/printer_data/backups/` bleiben erhalten, bis du sie löschst.

## Projektstruktur

```text
moonraker-backup/
├── README.md
├── LICENSE
├── .gitignore
├── component/
│   └── backup.py          # Moonraker-Komponente
├── scripts/
│   └── install.sh         # Installation + Config-Snippet
├── klipper_macro/
│   └── backup.cfg         # BACKUP_CONFIG Macro
├── ui/
│   └── index.html         # Einfache Web-UI
└── moonraker-example.conf # Beispiel-Einträge
```

## Lizenz

GNU GPLv3 – siehe [LICENSE](LICENSE).

## Credits

- [Moonraker](https://github.com/Arksine/moonraker)
- [moonraker-timelapse](https://github.com/mainsail-crew/moonraker-timelapse) (API-Muster)
- [Klipper-Backup](https://github.com/Staubgeborener/Klipper-Backup) (Idee Git-Backups)
