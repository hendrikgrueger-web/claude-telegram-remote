# Claude Code Remote Control via Telegram

## Deutsch

Ein Telegram-Bot, der Claude Code CLI remote von ueberall erreichbar macht — beim Spaziergang, im Gym, unterwegs.

### Was macht es?

Nachrichten an den Bot werden direkt an Claude Code CLI weitergeleitet. Antworten kommen sofort zurueck in Telegram — mit Live-Streaming, Workspace-Management und Modell-Auswahl.

**Sprachnachrichten** werden automatisch transkribiert (via OpenAI Whisper) und an Claude weitergeleitet — perfekt fuer unterwegs.

**Intelligente Bestaetigung:** Bei jeder Nachricht fasst Haiku kurz zusammen, was du willst und was Claude jetzt tun wird — keine generischen Nachrichten.

### Voraussetzungen

- macOS (getestet auf macOS 13+)
- Python 3.10+
- Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)
- Telegram Bot Token (von @BotFather)
- Deine Telegram User-ID (von @userinfobot)
- Optional: OpenAI API Key (fuer Sprachnachrichten)

### Installation

```bash
git clone https://github.com/hendrikgrueger-web/claude-telegram-remote.git
cd claude-telegram-remote
bash install.sh
```

Das Script:
- Findet Python 3.10+ automatisch (python3.12, python3.11, python3.10)
- Erstellt eine `.venv` und installiert Dependencies
- Findet den Claude CLI Pfad automatisch
- Fragt interaktiv nach Bot-Token und User-ID
- Richtet den launchd-Service ein (startet nach Login automatisch)

### Konfiguration

`install.sh` erstellt `.env` automatisch. Alle Optionen:

| Variable | Beschreibung | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Von @BotFather | (pflicht) |
| `ALLOWED_USER_ID` | Deine Telegram User-ID | (pflicht) |
| `DEFAULT_WORKSPACE_DIR` | Standard-Arbeitsverzeichnis | `~/Coding` |
| `CLAUDE_TIMEOUT_SECONDS` | Timeout pro Anfrage | `300` |
| `CLAUDE_BIN` | Absoluter Pfad zur Claude CLI | (auto-detected) |
| `OPENAI_API_KEY` | Fuer Sprachnachrichten (Whisper) | (optional) |

### Befehle

| Befehl | Funktion |
|--------|----------|
| `/ws list` | Alle Workspaces anzeigen |
| `/ws <name>` | Workspace wechseln / anlegen |
| `/ws <name> <pfad>` | Workspace mit Verzeichnis anlegen |
| `/ws delete <name>` | Workspace loeschen |
| `/sessions` | Workspaces als klickbare Buttons |
| `/model` | Aktuelles Modell anzeigen |
| `/model opus\|sonnet\|haiku` | Modell wechseln |
| `/plan` | Plan-Modus an/aus |
| `/clear` | Session loeschen, neu starten |
| `/compact` | Kontext zuruecksetzen |
| `/usage` | Token-Verbrauch anzeigen |
| `/skills` | Installierte Skills auflisten |
| `/rename <name>` | Workspace umbenennen |
| `/github` | Deine Repos anzeigen |
| `/stop` | Laufende Claude-Anfrage abbrechen |
| `/status` | Workspace, Verzeichnis, Claude-Version |
| `/help` | Alle Befehle |
| Beliebiger Text | Wird an Claude gesendet |
| 🎙️ Sprachnachricht | Wird transkribiert und an Claude gesendet |

### Watchdog

```bash
# Manuell ausfuehren
bash watchdog.sh

# Als Cronjob (alle 5 Min, selbstloeschend nach 3h)
EXPIRE=$(date -v+3H "+%s")
(crontab -l 2>/dev/null; echo "*/5 * * * * [ \$(date +\%s) -lt $EXPIRE ] && bash $(pwd)/watchdog.sh || (crontab -l | grep -v watchdog.sh | crontab -)") | crontab -
```

### Logs & Service-Verwaltung

```bash
# Logs live
tail -f ~/Library/Logs/claude-telegram/error.log

# Status
launchctl list | grep claude-telegram

# Neustart
launchctl kickstart -k gui/$(id -u)/com.claude-telegram-remote.bot

# Stop / Start
launchctl unload ~/Library/LaunchAgents/com.claude-telegram-remote.bot.plist
launchctl load ~/Library/LaunchAgents/com.claude-telegram-remote.bot.plist
```

### Sicherheit

- Nur deine Telegram User-ID kann den Bot nutzen
- Token in `.env` gespeichert (in `.gitignore`, wird nicht committet)

### Troubleshooting

**"claude: No such file or directory":**
CLAUDE_BIN in `.env` setzen. Pfad finden: `which claude`

**Bot reagiert nicht mehr:**
`launchctl kickstart -k gui/$(id -u)/com.claude-telegram-remote.bot` oder `bash watchdog.sh`

**Bot startet nicht nach Neustart:**
Der Bot startet nach User-Login automatisch. Kein Auto-Login noetig — einfach einloggen.
Pruefen: `launchctl list | grep claude-telegram`

### Lizenz

MIT

---

## English

A Telegram bot that gives you remote access to Claude Code CLI from anywhere — while walking, at the gym, on the go.

### What it does

Messages sent to the bot are forwarded directly to Claude Code CLI. Responses stream back to Telegram in real-time — with workspace management and model selection.

**Voice messages** are automatically transcribed (via OpenAI Whisper) and forwarded to Claude — perfect for on-the-go use.

**Smart acknowledgements:** Every message gets a brief Haiku-generated summary of what you want and what Claude will do — no generic filler messages.

### Prerequisites

- macOS (tested on macOS 13+)
- Python 3.10+
- Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)
- Telegram Bot Token (from @BotFather)
- Your Telegram User ID (from @userinfobot)
- Optional: OpenAI API Key (for voice messages)

### Installation

```bash
git clone https://github.com/hendrikgrueger-web/claude-telegram-remote.git
cd claude-telegram-remote
bash install.sh
```

The script:
- Finds Python 3.10+ automatically (python3.12, python3.11, python3.10)
- Creates a `.venv` and installs dependencies
- Auto-detects the Claude CLI path
- Interactively asks for bot token and user ID
- Sets up the launchd service (auto-starts after login)

### Configuration

`install.sh` creates `.env` automatically. All options:

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | From @BotFather | (required) |
| `ALLOWED_USER_ID` | Your Telegram User ID | (required) |
| `DEFAULT_WORKSPACE_DIR` | Default working directory | `~/Coding` |
| `CLAUDE_TIMEOUT_SECONDS` | Timeout per request | `300` |
| `CLAUDE_BIN` | Absolute path to Claude CLI | (auto-detected) |
| `OPENAI_API_KEY` | For voice messages (Whisper) | (optional) |

### Commands

| Command | Function |
|---------|----------|
| `/ws list` | Show all workspaces |
| `/ws <name>` | Switch to / create workspace |
| `/ws <name> <path>` | Create workspace with directory |
| `/ws delete <name>` | Delete workspace |
| `/sessions` | Workspaces as clickable buttons |
| `/model` | Show current model |
| `/model opus\|sonnet\|haiku` | Switch model |
| `/plan` | Toggle plan mode |
| `/clear` | Clear session, start fresh |
| `/compact` | Reset context |
| `/usage` | Show token usage |
| `/skills` | List installed skills |
| `/rename <name>` | Rename workspace |
| `/github` | List your repos |
| `/stop` | Cancel running Claude request |
| `/status` | Workspace, directory, Claude version |
| `/help` | Show all commands |
| Any text | Sent to Claude |
| 🎙️ Voice message | Transcribed and sent to Claude |

### Watchdog

```bash
# Run manually
bash watchdog.sh

# As cronjob (every 5 min, self-deleting after 3h)
EXPIRE=$(date -v+3H "+%s")
(crontab -l 2>/dev/null; echo "*/5 * * * * [ \$(date +\%s) -lt $EXPIRE ] && bash $(pwd)/watchdog.sh || (crontab -l | grep -v watchdog.sh | crontab -)") | crontab -
```

### Logs & Service Management

```bash
# Live logs
tail -f ~/Library/Logs/claude-telegram/error.log

# Status
launchctl list | grep claude-telegram

# Restart
launchctl kickstart -k gui/$(id -u)/com.claude-telegram-remote.bot

# Stop / Start
launchctl unload ~/Library/LaunchAgents/com.claude-telegram-remote.bot.plist
launchctl load ~/Library/LaunchAgents/com.claude-telegram-remote.bot.plist
```

### Security

- Only your Telegram User ID can interact with the bot
- Token stored in `.env` (in `.gitignore`, never committed)

### Troubleshooting

**"claude: No such file or directory":**
Set CLAUDE_BIN in `.env`. Find your path: `which claude`

**Bot stops responding:**
`launchctl kickstart -k gui/$(id -u)/com.claude-telegram-remote.bot` or `bash watchdog.sh`

**Bot doesn't start after reboot:**
The bot starts automatically after user login. No auto-login needed — just log in.
Check: `launchctl list | grep claude-telegram`

### License

MIT
