# CLAUDE.md — Claude Telegram Remote Control

## Was ist das?

Telegram-Bot als privates Remote-Interface zu Claude Code. Läuft als launchd-Dienst auf dem Mac mini.

## Architektur

| Datei | Zweck |
|-------|-------|
| `bot.py` | Telegram-Handler, Command-Handler, Entry Point |
| `workspace.py` | WorkspaceManager: Workspace-State (JSON-Persistenz) |
| `claude_runner.py` | ClaudeRunner: claude CLI Subprocess + Streaming; OutputStreamer: batched Edits |
| `start.sh` | launchd Wrapper (lädt .env, absoluter Python-Pfad) |
| `com.hendrik.claude-telegram.plist` | launchd LaunchAgent Definition |
| `install.sh` | Einmaliges Setup-Script |
| `SETUP_PROMPT.md` | Fertiger Prompt für Claude Code Setup |

## State-Dateien (nicht im Repo)

- `~/.config/claude-telegram/workspaces.json` — Workspace-State
- `~/Library/Logs/claude-telegram/` — Logs
- `.env` — Secrets (TELEGRAM_BOT_TOKEN, ALLOWED_USER_ID, DEFAULT_WORKSPACE_DIR, CLAUDE_TIMEOUT_SECONDS)

## Service-Verwaltung

```bash
# Status
launchctl list | grep claude-telegram

# Logs live
tail -f ~/Library/Logs/claude-telegram/bot.log

# Neustart
launchctl unload ~/Library/LaunchAgents/com.hendrik.claude-telegram.plist
launchctl load ~/Library/LaunchAgents/com.hendrik.claude-telegram.plist
```

## Entwicklung / Tests

```bash
pip3 install -r requirements-dev.txt
pytest tests/ -v
```

## Telegram-Befehle

| Befehl | Funktion |
|--------|---------|
| `/ws list` | Alle Workspaces anzeigen |
| `/ws <name>` | Workspace wechseln / anlegen |
| `/ws <name> <pfad>` | Workspace mit Verzeichnis anlegen |
| `/ws delete <name>` | Workspace löschen |
| `/stop` | Laufende Claude-Anfrage abbrechen |
| `/status` | Workspace, Verzeichnis, Claude-Version |
| `/help` | Alle Befehle |
