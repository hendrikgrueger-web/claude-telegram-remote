# CLAUDE.md — Claude Telegram Remote Control

## Was ist das?

Telegram-Bot als privates Remote-Interface zu Claude Code. Laeuft als launchd-Dienst auf macOS.
Steuere Claude Code von ueberall — beim Spazierengehen, im Gym, unterwegs.

## Architektur

| Datei | Zweck |
|-------|-------|
| `bot.py` | Telegram-Handler, Command-Handler, Entry Point |
| `workspace.py` | WorkspaceManager: Workspace-State + Model-Auswahl (JSON-Persistenz) |
| `claude_runner.py` | ClaudeRunner: claude CLI Subprocess + Streaming; OutputStreamer: batched Edits |
| `start.sh` | launchd Wrapper (laedt .env, startet bot.py via .venv) |
| `com.hendrik.claude-telegram.plist` | launchd LaunchAgent Definition |
| `install.sh` | Setup: venv erstellen, Dependencies, Claude CLI finden, launchd einrichten |

## Installation

```bash
git clone <repo-url>
cd claude-telegram-remote
bash install.sh
```

install.sh:
1. Findet Python 3.10+ (probiert python3.12, python3.11, python3.10, python3)
2. Erstellt `.venv` und installiert Dependencies dort
3. Findet Claude CLI automatisch (oder manuell via CLAUDE_BIN in .env)
4. Fragt interaktiv nach Bot-Token und User-ID
5. Richtet launchd-Service ein

## Bekannte Fixes

- **"claude: No such file or directory"**: CLAUDE_BIN=/absoluter/pfad/zu/claude in .env setzen
- **"afk-mode beta header"**: CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1 in .env (standardmaessig gesetzt)
- **Python "externally managed"**: install.sh nutzt venv statt direktem pip install

## State-Dateien (nicht im Repo)

- `~/.config/claude-telegram/workspaces.json` — Workspace-State + Model pro Workspace
- `~/Library/Logs/claude-telegram/` — Logs (error.log fuer Bot-Output)
- `.env` — Secrets (TELEGRAM_BOT_TOKEN, ALLOWED_USER_ID, CLAUDE_BIN, etc.)

## Service-Verwaltung

```bash
# Status
launchctl list | grep claude-telegram

# Logs live
tail -f ~/Library/Logs/claude-telegram/error.log

# Neustart
launchctl kickstart -k gui/$(id -u)/com.hendrik.claude-telegram

# Stop / Start
launchctl unload ~/Library/LaunchAgents/com.hendrik.claude-telegram.plist
launchctl load ~/Library/LaunchAgents/com.hendrik.claude-telegram.plist
```

## Telegram-Befehle

| Befehl | Funktion |
|--------|---------|
| `/ws list` | Alle Workspaces anzeigen |
| `/ws <name>` | Workspace wechseln / anlegen |
| `/ws <name> <pfad>` | Workspace mit Verzeichnis anlegen |
| `/ws delete <name>` | Workspace loeschen |
| `/model` | Aktuelles Modell anzeigen |
| `/model opus\|sonnet\|haiku` | Modell wechseln |
| `/clear` | Session loeschen, neu starten |
| `/compact` | Kontext zuruecksetzen |
| `/stop` | Laufende Claude-Anfrage abbrechen |
| `/status` | Workspace, Verzeichnis, Claude-Version |
| `/help` | Alle Befehle |

## Entwicklung / Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest tests/ -v
```
