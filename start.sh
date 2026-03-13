#!/bin/bash
# start.sh — launchd Wrapper: lädt .env und startet bot.py
# PYTHON_BIN wird von install.sh mit dem absoluten Pfad ersetzt.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# .env laden
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/.env"
    set +a
fi

exec PYTHON_BIN "$SCRIPT_DIR/bot.py"
