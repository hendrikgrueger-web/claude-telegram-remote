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

# 1. Python-Version prüfen
PYTHON_BIN="$(which python3)"
PYTHON_VERSION=$("$PYTHON_BIN" -c "import sys; print(sys.version_info.minor)")
if [ "$PYTHON_VERSION" -lt 10 ]; then
    echo "❌ Python 3.10+ erforderlich. Installiert: $($PYTHON_BIN --version)"
    exit 1
fi
echo "✅ $($PYTHON_BIN --version) unter $PYTHON_BIN"

# 2. start.sh mit absolutem Python-Pfad patchen
sed -i '' "s|PYTHON_BIN|$PYTHON_BIN|g" "$INSTALL_DIR/start.sh"
echo "✅ start.sh mit Python-Pfad konfiguriert"

# 3. Dependencies installieren
echo "📦 Installiere Dependencies..."
"$PYTHON_BIN" -m pip install -r "$INSTALL_DIR/requirements.txt" --quiet
echo "✅ Dependencies installiert"

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

# 9. Auto-Login Hinweis
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " ⚠️  WICHTIG: Auto-Login aktivieren!     "
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Der Bot startet nur nach User-Login."
echo " Für 24/7-Betrieb bitte aktivieren:"
echo " Systemeinstellungen → Allgemein → Autom. Anmelden"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " ✅ Installation abgeschlossen!           "
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Logs: tail -f $LOGS_DIR/bot.log"
echo " Stop: launchctl unload $PLIST_DEST"
echo " Start: launchctl load $PLIST_DEST"
echo ""
