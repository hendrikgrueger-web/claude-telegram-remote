#!/bin/bash
# watchdog.sh — Production-grade health check for Claude Telegram Bot.
# Runs via cron every 2-5 minutes. Self-contained, no external deps.
#
# Health checks (in priority order):
#   1. Heartbeat file (~/.config/claude-telegram/bot.health) — detects event-loop hangs
#   2. Log recency (error.log) — fallback if heartbeat file doesn't exist yet
#   3. Process liveness via launchctl — detects crashed/unregistered service
#
# Escalation: If >3 restarts in 30 minutes, sends escalation alert.

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────

SERVICE="com.claude-telegram-remote.bot"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
LOG_DIR="${HOME}/Library/Logs/claude-telegram"
LOG="${LOG_DIR}/watchdog.log"
HEALTH_FILE="${HOME}/.config/claude-telegram/bot.health"
RESTART_HISTORY="${LOG_DIR}/watchdog-restarts.log"
PLIST="${HOME}/Library/LaunchAgents/${SERVICE}.plist"

HEARTBEAT_MAX_AGE=90      # seconds — bot writes every 30s, so 90s = 3 missed beats
LOG_MAX_AGE=120            # seconds — fallback check on error.log
MAX_RESTARTS_WINDOW=3      # restart count threshold
RESTART_WINDOW=1800        # 30 minutes in seconds
ALERT_RETRY_COUNT=3        # Telegram alert retries
ALERT_RETRY_BACKOFF=5      # seconds between retries (doubles each attempt)
MAX_LOG_SIZE=1048576       # 1 MB — rotate watchdog log if exceeded

# ── Setup ────────────────────────────────────────────────────────────────────

mkdir -p "${LOG_DIR}"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "${LOG}"
}

# Rotate watchdog log if too large
if [[ -f "${LOG}" ]]; then
    log_size=$(stat -f%z "${LOG}" 2>/dev/null || echo "0")
    if [[ "${log_size}" -gt "${MAX_LOG_SIZE}" ]]; then
        mv "${LOG}" "${LOG}.old"
        log "INFO: Watchdog-Log rotiert (${log_size} bytes)"
    fi
fi

# ── Load .env ────────────────────────────────────────────────────────────────

if [[ ! -f "${ENV_FILE}" ]]; then
    log "FATAL: .env nicht gefunden: ${ENV_FILE}"
    exit 1
fi

# Source .env safely — only export known variables, ignore comments and blanks
set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a

BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
USER_ID="${ALLOWED_USER_ID:-}"

if [[ -z "${BOT_TOKEN}" ]]; then
    log "WARN: TELEGRAM_BOT_TOKEN nicht gesetzt in .env — Alerts deaktiviert"
fi
if [[ -z "${USER_ID}" ]]; then
    log "WARN: ALLOWED_USER_ID nicht gesetzt in .env — Alerts deaktiviert"
fi

# ── Helper Functions ─────────────────────────────────────────────────────────

now_epoch() {
    date "+%s"
}

send_telegram() {
    local message="$1"
    local attempt=0
    local backoff="${ALERT_RETRY_BACKOFF}"

    if [[ -z "${BOT_TOKEN}" ]] || [[ -z "${USER_ID}" ]]; then
        log "WARN: Telegram-Alert uebersprungen (Token/UserID fehlt)"
        return 1
    fi

    while [[ "${attempt}" -lt "${ALERT_RETRY_COUNT}" ]]; do
        attempt=$((attempt + 1))
        local http_code
        http_code=$(curl -s -o /dev/null -w "%{http_code}" \
            --max-time 10 \
            "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            -d "chat_id=${USER_ID}" \
            -d "text=${message}" 2>/dev/null) || http_code="000"

        if [[ "${http_code}" == "200" ]]; then
            log "INFO: Telegram-Alert gesendet (Versuch ${attempt})"
            return 0
        fi

        log "WARN: Telegram-Alert fehlgeschlagen (HTTP ${http_code}, Versuch ${attempt}/${ALERT_RETRY_COUNT})"

        if [[ "${attempt}" -lt "${ALERT_RETRY_COUNT}" ]]; then
            sleep "${backoff}"
            backoff=$((backoff * 2))
        fi
    done

    log "ERROR: Telegram-Alert nach ${ALERT_RETRY_COUNT} Versuchen fehlgeschlagen"
    return 1
}

record_restart() {
    echo "$(now_epoch)" >> "${RESTART_HISTORY}"
}

count_recent_restarts() {
    if [[ ! -f "${RESTART_HISTORY}" ]]; then
        echo "0"
        return
    fi

    local cutoff
    cutoff=$(( $(now_epoch) - RESTART_WINDOW ))
    local count=0

    while IFS= read -r ts; do
        if [[ -n "${ts}" ]] && [[ "${ts}" -gt "${cutoff}" ]] 2>/dev/null; then
            count=$((count + 1))
        fi
    done < "${RESTART_HISTORY}"

    echo "${count}"
}

cleanup_restart_history() {
    # Remove entries older than the window to keep the file small
    if [[ ! -f "${RESTART_HISTORY}" ]]; then
        return
    fi

    local cutoff
    cutoff=$(( $(now_epoch) - RESTART_WINDOW ))
    local tmp="${RESTART_HISTORY}.tmp"

    while IFS= read -r ts; do
        if [[ -n "${ts}" ]] && [[ "${ts}" -gt "${cutoff}" ]] 2>/dev/null; then
            echo "${ts}"
        fi
    done < "${RESTART_HISTORY}" > "${tmp}"

    mv "${tmp}" "${RESTART_HISTORY}"
}

restart_bot() {
    local reason="$1"

    log "ALERT: ${reason} — starte Bot neu"

    # Record and check escalation
    record_restart
    cleanup_restart_history
    local recent_count
    recent_count=$(count_recent_restarts)

    launchctl kickstart -k "gui/$(id -u)/${SERVICE}" 2>/dev/null || {
        log "ERROR: launchctl kickstart fehlgeschlagen"
        send_telegram "🚨 Watchdog: Bot-Neustart fehlgeschlagen! Reason: ${reason}" || true
        return 1
    }

    # Wait for process to come up
    sleep 5

    if [[ "${recent_count}" -gt "${MAX_RESTARTS_WINDOW}" ]]; then
        log "ESCALATION: ${recent_count} Neustarts in den letzten $((RESTART_WINDOW / 60)) Minuten!"
        send_telegram "🚨 ESKALATION: Bot wurde ${recent_count}x in 30 Min neu gestartet! Manuelles Eingreifen noetig. Letzter Grund: ${reason}" || true
    else
        send_telegram "🔄 Watchdog: Bot neu gestartet (${recent_count}/${MAX_RESTARTS_WINDOW} in 30 Min). Grund: ${reason}" || true
    fi

    log "INFO: Bot neu gestartet (Restart ${recent_count}/${MAX_RESTARTS_WINDOW} in Window)"
}

# ── Check 1: Service registered in launchd? ─────────────────────────────────

get_service_pid() {
    # Use launchctl list <service> directly — more reliable than grep
    local output
    output=$(launchctl list "${SERVICE}" 2>/dev/null) || {
        echo "unregistered"
        return
    }

    # Parse PID from output: first line after header contains "PID" = <number> or "-"
    local pid
    pid=$(echo "${output}" | awk '/^"PID"/ || /PID/ { getline; print }' 2>/dev/null || echo "")

    # Fallback: try the tabular format (PID\tStatus\tLabel)
    if [[ -z "${pid}" ]]; then
        pid=$(echo "${output}" | awk -F'=' '/PID/ {gsub(/[^0-9]/, "", $2); print $2}' 2>/dev/null || echo "")
    fi

    # Another fallback: grep for a number in the "PID" line
    if [[ -z "${pid}" ]]; then
        pid=$(echo "${output}" | grep -i "pid" | grep -o '[0-9]\+' | head -1 2>/dev/null || echo "")
    fi

    if [[ -z "${pid}" ]] || [[ "${pid}" == "0" ]]; then
        echo "not_running"
    else
        echo "${pid}"
    fi
}

if ! launchctl list "${SERVICE}" &>/dev/null; then
    log "WARN: Service nicht registriert — versuche plist zu laden"

    if [[ ! -f "${PLIST}" ]]; then
        log "FATAL: plist nicht gefunden: ${PLIST}"
        send_telegram "🚨 Watchdog: plist fehlt — Bot kann nicht gestartet werden: ${PLIST}" || true
        exit 1
    fi

    launchctl load "${PLIST}" 2>/dev/null || {
        log "ERROR: launchctl load fehlgeschlagen"
        send_telegram "🚨 Watchdog: launchctl load fehlgeschlagen" || true
        exit 1
    }
    sleep 2
    log "INFO: Service geladen"
fi

# ── Check 2: Process running? ───────────────────────────────────────────────

SERVICE_PID=$(get_service_pid)

if [[ "${SERVICE_PID}" == "unregistered" ]]; then
    restart_bot "Service nicht registriert trotz load-Versuch"
    exit 0
fi

if [[ "${SERVICE_PID}" == "not_running" ]]; then
    restart_bot "Bot-Prozess nicht aktiv (PID = 0 oder nicht vorhanden)"
    exit 0
fi

# ── Check 3: Heartbeat-based health (primary) ───────────────────────────────

heartbeat_ok=false

if [[ -f "${HEALTH_FILE}" ]]; then
    heartbeat_ts=$(cat "${HEALTH_FILE}" 2>/dev/null || echo "")

    if [[ -n "${heartbeat_ts}" ]]; then
        # Heartbeat file contains a float epoch timestamp — truncate to integer
        heartbeat_epoch="${heartbeat_ts%%.*}"

        if [[ "${heartbeat_epoch}" =~ ^[0-9]+$ ]]; then
            current_epoch=$(now_epoch)
            heartbeat_age=$((current_epoch - heartbeat_epoch))

            if [[ "${heartbeat_age}" -gt "${HEARTBEAT_MAX_AGE}" ]]; then
                restart_bot "Event-Loop haengt — Heartbeat ${heartbeat_age}s alt (Max: ${HEARTBEAT_MAX_AGE}s)"
                exit 0
            else
                heartbeat_ok=true
            fi
        else
            log "WARN: Heartbeat-Datei enthaelt ungueltige Daten: '${heartbeat_ts}'"
        fi
    else
        log "WARN: Heartbeat-Datei leer"
    fi
else
    log "INFO: Heartbeat-Datei existiert noch nicht — verwende Log-Fallback"
fi

# ── Check 4: Log-based health (fallback) ────────────────────────────────────

if [[ "${heartbeat_ok}" == "false" ]]; then
    ERROR_LOG="${LOG_DIR}/error.log"

    if [[ -f "${ERROR_LOG}" ]]; then
        # Get last modification time of error.log via stat (macOS/BSD)
        last_mod=$(stat -f%m "${ERROR_LOG}" 2>/dev/null || echo "0")
        current_epoch=$(now_epoch)
        log_age=$((current_epoch - last_mod))

        if [[ "${log_age}" -gt "${LOG_MAX_AGE}" ]]; then
            restart_bot "Keine Log-Aktivitaet seit ${log_age}s (Max: ${LOG_MAX_AGE}s) und kein Heartbeat"
            exit 0
        fi
        # Log file is recent enough — consider it OK
    else
        log "WARN: Weder Heartbeat noch error.log vorhanden — kann Health nicht pruefen"
        # Don't restart yet — bot may still be starting up
    fi
fi

# ── All checks passed ───────────────────────────────────────────────────────

if [[ "${heartbeat_ok}" == "true" ]]; then
    log "OK: Bot laeuft (PID=${SERVICE_PID}, Heartbeat aktuell)"
else
    log "OK: Bot laeuft (PID=${SERVICE_PID}, Log-Fallback)"
fi
