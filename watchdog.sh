#!/bin/bash
# watchdog.sh — Prueft ob der Telegram-Bot laeuft und startet ihn ggf. neu.
# Wird per Cronjob alle 5 Minuten aufgerufen.

set -euo pipefail

SERVICE="com.claude-telegram-remote.bot"
LOG_DIR="$HOME/Library/Logs/claude-telegram"
LOG="$LOG_DIR/watchdog.log"
BOT_TOKEN="$(grep TELEGRAM_BOT_TOKEN "$(dirname "$0")/.env" | cut -d= -f2)"
USER_ID="$(grep ALLOWED_USER_ID "$(dirname "$0")/.env" | cut -d= -f2)"

mkdir -p "$LOG_DIR"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG"; }

# 1. Pruefe ob Prozess laeuft
if ! launchctl list | grep -q "$SERVICE"; then
    log "WARN: Service nicht registriert — lade plist"
    launchctl load "$HOME/Library/LaunchAgents/${SERVICE}.plist" 2>/dev/null || true
    sleep 2
fi

PID=$(launchctl list | grep "$SERVICE" | awk '{print $1}')
if [ "$PID" = "-" ] || [ -z "$PID" ]; then
    log "ALERT: Bot-Prozess nicht aktiv — starte neu"
    launchctl kickstart -k "gui/$(id -u)/$SERVICE"
    sleep 5
    # Benachrichtigung via Telegram
    if [ -n "$BOT_TOKEN" ] && [ -n "$USER_ID" ]; then
        curl -s "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            -d "chat_id=${USER_ID}" \
            -d "text=🔄 Watchdog: Bot war down und wurde neu gestartet." > /dev/null 2>&1
    fi
    log "INFO: Bot neu gestartet"
    exit 0
fi

# 2. Pruefe ob der Bot tatsaechlich pollt (letzte Log-Zeile < 2 Min alt)
LAST_LOG=$(tail -1 "$LOG_DIR/error.log" 2>/dev/null || echo "")
if [ -n "$LAST_LOG" ]; then
    LAST_TS=$(echo "$LAST_LOG" | grep -oP '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}' 2>/dev/null || echo "")
    if [ -n "$LAST_TS" ]; then
        LAST_EPOCH=$(date -j -f "%Y-%m-%d %H:%M:%S" "$LAST_TS" "+%s" 2>/dev/null || echo "0")
        NOW_EPOCH=$(date "+%s")
        DIFF=$((NOW_EPOCH - LAST_EPOCH))
        if [ "$DIFF" -gt 120 ]; then
            log "ALERT: Letzte Log-Zeile ist ${DIFF}s alt — Bot haengt, starte neu"
            launchctl kickstart -k "gui/$(id -u)/$SERVICE"
            sleep 5
            if [ -n "$BOT_TOKEN" ] && [ -n "$USER_ID" ]; then
                curl -s "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
                    -d "chat_id=${USER_ID}" \
                    -d "text=🔄 Watchdog: Bot reagierte nicht mehr und wurde neu gestartet." > /dev/null 2>&1
            fi
            log "INFO: Bot nach Hang neu gestartet"
            exit 0
        fi
    fi
fi

log "OK: Bot laeuft (PID=$PID)"
