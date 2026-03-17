#!/bin/bash
# start.sh — launchd Wrapper: lädt .env, validiert Umgebung, startet bot.py via venv
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$HOME/Library/Logs/claude-telegram"
STARTUP_LOG="$LOG_DIR/startup.log"

# Explicit PATH — include Homebrew (Apple Silicon + Intel) and system defaults
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$STARTUP_LOG"
}

die() {
    log "FATAL: $*"
    echo "FATAL: $*" >&2
    exit 1
}

log "--- Starting claude-telegram-remote ---"
log "SCRIPT_DIR=$SCRIPT_DIR"
log "PATH=$PATH"

# --- Validate .env ---
ENV_FILE="$SCRIPT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    die ".env not found at $ENV_FILE — copy .env.example and fill in your values"
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a
log ".env loaded from $ENV_FILE"

# --- Validate required environment variables ---
: "${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN is not set in .env}"
: "${ALLOWED_USER_ID:?ALLOWED_USER_ID is not set in .env}"
: "${CLAUDE_BIN:?CLAUDE_BIN is not set in .env}"

if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    die "TELEGRAM_BOT_TOKEN is empty in .env"
fi
if [ -z "$ALLOWED_USER_ID" ]; then
    die "ALLOWED_USER_ID is empty in .env"
fi
if [ -z "$CLAUDE_BIN" ]; then
    die "CLAUDE_BIN is empty in .env"
fi
log "Required env vars validated (TELEGRAM_BOT_TOKEN=***redacted***, ALLOWED_USER_ID=$ALLOWED_USER_ID, CLAUDE_BIN=$CLAUDE_BIN)"

# --- Validate CLAUDE_BIN ---
if [[ "$CLAUDE_BIN" == /* ]]; then
    # Absolute path — must exist and be executable
    if [ ! -x "$CLAUDE_BIN" ]; then
        die "CLAUDE_BIN=$CLAUDE_BIN does not exist or is not executable"
    fi
else
    # Relative/bare command — check via PATH
    if ! command -v "$CLAUDE_BIN" &>/dev/null; then
        die "CLAUDE_BIN=$CLAUDE_BIN not found in PATH"
    fi
fi
log "CLAUDE_BIN validated: $(command -v "$CLAUDE_BIN" 2>/dev/null || echo "$CLAUDE_BIN")"

# --- Validate .venv ---
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python3"
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    die ".venv directory not found at $SCRIPT_DIR/.venv — run install.sh first"
fi
if [ ! -x "$VENV_PYTHON" ]; then
    die "python3 not found or not executable at $VENV_PYTHON — recreate venv with install.sh"
fi
log "venv python: $VENV_PYTHON ($($VENV_PYTHON --version 2>&1))"

# --- Launch ---
log "Launching bot.py with exec"
exec "$VENV_PYTHON" "$SCRIPT_DIR/bot.py"
