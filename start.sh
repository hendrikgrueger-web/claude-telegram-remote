#!/bin/bash
# start.sh — launchd Wrapper: lädt .env und startet bot.py via venv
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# .env laden
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/.env"
    set +a
fi

exec "$SCRIPT_DIR/.venv/bin/python3" "$SCRIPT_DIR/bot.py"
