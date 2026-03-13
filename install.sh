#!/bin/bash
# install.sh — Einmaliges Setup für Claude Telegram Remote Control
set -e

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGS_DIR="$HOME/Library/Logs/claude-telegram"
PLIST_NAME="com.hendrik.claude-telegram"
PLIST_SRC="$INSTALL_DIR/$PLIST_NAME.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
CONFIG_DIR="$HOME/.config/claude-telegram"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Claude Telegram Remote — Installation  "
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. Python 3.10+ finden
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "0")
        if [ "$ver" -ge 10 ]; then
            PYTHON_BIN="$(command -v "$candidate")"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Python 3.10+ erforderlich. Installiere z.B.: brew install python@3.12"
    exit 1
fi
echo "✅ $($PYTHON_BIN --version) unter $PYTHON_BIN"

# 2. Virtualenv erstellen und Dependencies installieren
echo "📦 Erstelle Virtualenv und installiere Dependencies..."
"$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --quiet
echo "✅ Dependencies in .venv installiert"

# 3. Claude CLI finden
CLAUDE_PATH="$(command -v claude 2>/dev/null || echo "")"
if [ -z "$CLAUDE_PATH" ]; then
    # Typische Installationspfade durchsuchen
    for p in "$HOME/.local/bin/claude" "/usr/local/bin/claude" "$HOME/.npm-global/bin/claude"; do
        if [ -x "$p" ]; then
            CLAUDE_PATH="$p"
            break
        fi
    done
fi
if [ -z "$CLAUDE_PATH" ]; then
    echo "⚠️  Claude CLI nicht gefunden. Bitte CLAUDE_BIN in .env manuell setzen."
else
    echo "✅ Claude CLI: $CLAUDE_PATH"
fi

# 4. .env einrichten
if [ ! -f "$INSTALL_DIR/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    echo ""
    echo "📝 Bitte .env befüllen:"
    echo ""
    read -p "   Telegram Bot Token (von @BotFather): " BOT_TOKEN
    read -p "   Deine Telegram User-ID (von @userinfobot): " USER_ID
    read -p "   Standard-Verzeichnis [~/Coding]: " WORK_DIR
    WORK_DIR="${WORK_DIR:-~/Coding}"

    sed -i '' "s|your_token_here|$BOT_TOKEN|" "$INSTALL_DIR/.env"
    sed -i '' "s|123456789|$USER_ID|" "$INSTALL_DIR/.env"
    sed -i '' "s|~/Coding|$WORK_DIR|" "$INSTALL_DIR/.env"

    # Claude-Pfad automatisch eintragen
    if [ -n "$CLAUDE_PATH" ]; then
        sed -i '' "s|# CLAUDE_BIN=|CLAUDE_BIN=$CLAUDE_PATH|" "$INSTALL_DIR/.env"
    fi
    echo "✅ .env konfiguriert"
else
    echo "✅ .env bereits vorhanden"
fi

# 5. Config-Verzeichnis + workspaces.json initialisieren
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/workspaces.json" ]; then
    WORK_DIR_EXPANDED=$(eval echo "$(grep DEFAULT_WORKSPACE_DIR "$INSTALL_DIR/.env" | cut -d= -f2)")
    cat > "$CONFIG_DIR/workspaces.json" << EOF
{
  "active": "main",
  "workspaces": {
    "main": {
      "directory": "$WORK_DIR_EXPANDED",
      "session_id": null,
      "last_used": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    }
  }
}
EOF
    echo "✅ Workspace-Config initialisiert"
fi

# 6. Log-Verzeichnis anlegen
mkdir -p "$LOGS_DIR"

# 7. Plist installieren (Pfade ersetzen)
sed "s|INSTALL_DIR|$INSTALL_DIR|g; s|LOGS_DIR|$LOGS_DIR|g" \
    "$PLIST_SRC" > "$PLIST_DEST"
echo "✅ launchd Plist installiert: $PLIST_DEST"

# 8. Service laden
if launchctl list | grep -q "$PLIST_NAME" 2>/dev/null; then
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi
launchctl load "$PLIST_DEST"
echo "✅ Service gestartet"

# 9. Hinweis
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " ✅ Installation abgeschlossen!           "
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo " Der Bot startet nach User-Login automatisch."
echo " Nach macOS-Neustart einmal einloggen."
echo ""
echo " Logs:    tail -f $LOGS_DIR/error.log"
echo " Stop:    launchctl unload $PLIST_DEST"
echo " Start:   launchctl load $PLIST_DEST"
echo " Neustart: launchctl kickstart -k gui/\$(id -u)/$PLIST_NAME"
echo ""
