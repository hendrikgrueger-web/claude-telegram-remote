# Claude Code Remote Control via Telegram

## Deutsch

Ein Telegram-Bot, der Claude Code CLI remote von ueberall erreichbar macht — beim Spaziergang, im Gym, unterwegs.

### Was macht es?

Nachrichten an den Bot werden direkt an Claude Code CLI weitergeleitet. Antworten kommen sofort zurueck in Telegram — mit Live-Streaming, Workspace-Management und Modell-Auswahl.

### Voraussetzungen

- macOS (getestet auf macOS 13+)
- Python 3.10+
- Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)
- Telegram Bot Token (von @BotFather)
- Deine Telegram User-ID (von @userinfobot)

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
| `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` | Workaround fuer Beta-Header | `1` |

### Befehle

| Befehl | Funktion |
|--------|----------|
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
| Beliebiger Text | Wird an Claude gesendet |

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

**"afk-mode beta header" Error:**
Bereits standardmaessig geloest: `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` ist in `.env.example`.

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

### Prerequisites

- macOS (tested on macOS 13+)
- Python 3.10+
- Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)
- Telegram Bot Token (from @BotFather)
- Your Telegram User ID (from @userinfobot)

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
| `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` | Workaround for beta headers | `1` |

### Commands

| Command | Function |
|---------|----------|
| `/ws list` | Show all workspaces |
| `/ws <name>` | Switch to / create workspace |
| `/ws <name> <path>` | Create workspace with directory |
| `/ws delete <name>` | Delete workspace |
| `/model` | Show current model |
| `/model opus\|sonnet\|haiku` | Switch model |
| `/clear` | Clear session, start fresh |
| `/compact` | Reset context |
| `/stop` | Cancel running Claude request |
| `/status` | Workspace, directory, Claude version |
| `/help` | Show all commands |
| Any text | Sent to Claude |

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

**"afk-mode beta header" error:**
Already solved by default: `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` is set in `.env.example`.

**Bot doesn't start after reboot:**
The bot starts automatically after user login. No auto-login needed — just log in.
Check: `launchctl list | grep claude-telegram`

### License

MIT
