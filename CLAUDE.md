# CLAUDE.md — Claude Telegram Remote Control

## Was ist das?

Telegram-Bot als privates Remote-Interface zu Claude Code. Laeuft als launchd-Dienst auf macOS.
Steuere Claude Code von ueberall — beim Spazierengehen, im Gym, unterwegs.

## Architektur

| Datei | Zweck |
|-------|-------|
| `bot.py` | Telegram-Handler, Command-Handler, Voice-Handler, Entry Point |
| `workspace.py` | WorkspaceManager: Workspace-State + Model-Auswahl (JSON-Persistenz) |
| `claude_runner.py` | ClaudeRunner: claude CLI Subprocess + Streaming; OutputStreamer: batched Edits |
| `acknowledgements.py` | Haiku-basierte Task-Zusammenfassung als Empfangsbestaetigung |
| `transcriber.py` | Sprachnachrichten-Transkription via OpenAI Whisper API |
| `event_formatter.py` | Smart-Level Event-Formatter fuer Telegram (Thinking, Tool-Calls, Antwort) |
| `permission_server.py` | Permission-Server fuer Tool-Genehmigungen via Telegram-Buttons |
| `watchdog.sh` | Health-Check Script: prueft ob Bot laeuft, startet ggf. neu |
| `start.sh` | launchd Wrapper (laedt .env, startet bot.py via .venv) |
| `com.claude-telegram-remote.bot.plist` | launchd LaunchAgent Definition |
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

## .env Konfiguration

```
TELEGRAM_BOT_TOKEN=...        # Von @BotFather
ALLOWED_USER_ID=...           # Deine Telegram User-ID
CLAUDE_BIN=/pfad/zu/claude    # Claude CLI Pfad
OPENAI_API_KEY=sk-...         # Fuer Sprachnachrichten (Whisper API)
```

## Bekannte Fixes

- **"claude: No such file or directory"**: CLAUDE_BIN=/absoluter/pfad/zu/claude in .env setzen
- **"afk-mode beta header"**: CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1 in .env (standardmaessig gesetzt)
- **Python "externally managed"**: install.sh nutzt venv statt direktem pip install
- **Bot reagiert nicht mehr**: `launchctl kickstart -k gui/$(id -u)/com.claude-telegram-remote.bot` oder watchdog.sh nutzen

## State-Dateien (nicht im Repo)

- `~/.config/claude-telegram/workspaces.json` — Workspace-State + Model pro Workspace
- `~/Library/Logs/claude-telegram/` — Logs (error.log fuer Bot-Output, watchdog.log)
- `.env` — Secrets (TELEGRAM_BOT_TOKEN, ALLOWED_USER_ID, CLAUDE_BIN, OPENAI_API_KEY)

## Service-Verwaltung

```bash
# Status
launchctl list | grep claude-telegram

# Logs live
tail -f ~/Library/Logs/claude-telegram/error.log

# Neustart
launchctl kickstart -k gui/$(id -u)/com.claude-telegram-remote.bot

# Stop / Start
launchctl unload ~/Library/LaunchAgents/com.claude-telegram-remote.bot.plist
launchctl load ~/Library/LaunchAgents/com.claude-telegram-remote.bot.plist

# Watchdog (manuell)
bash watchdog.sh
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
| 🎙️ Sprachnachricht | Wird transkribiert und an Claude weitergeleitet |

## Website / README

**Regel:** Bei neuen Features IMMER die GitHub-Website (README) in **beiden Sprachen** (Deutsch + Englisch) aktualisieren.

## Entwicklung / Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest tests/ -v
```
