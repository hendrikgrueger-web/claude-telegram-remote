#!/usr/bin/env python3
"""Claude Code PreToolUse Hook.

Liest Tool-Info von stdin (JSON), POST an Permission-Server,
gibt Decision auf stdout aus (nur bei "block" — kein Output = allow).

Konfiguration:
  PERMISSION_SERVER_PORT  Port des Permission-Servers (default: 7429)

Bei jedem Fehler wird kein Output produziert → Claude darf fortfahren (safe default).
"""

import json
import os
import sys
import urllib.request
import urllib.error

PERMISSION_SERVER_PORT = os.getenv("PERMISSION_SERVER_PORT", "7429")
PERMISSION_SERVER_URL = f"http://127.0.0.1:{PERMISSION_SERVER_PORT}"


def main() -> None:
    # Nur im Bot-Kontext aktiv (nicht bei lokalen Claude Code Sessions)
    if os.getenv("CLAUDE_TELEGRAM_ACTIVE") != "1":
        return

    # Tool-Info von stdin lesen (Claude CLI sendet JSON)
    try:
        tool_info = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        return  # Kein/ungueltiger Input → allow (default)

    payload = json.dumps({
        "tool_name": tool_info.get("tool_name", "unknown"),
        "tool_input": tool_info.get("tool_input", {}),
    }).encode("utf-8")

    req = urllib.request.Request(
        PERMISSION_SERVER_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        # Timeout 300s (DESTRUCTIVE kann ewig warten — User muss entscheiden)
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read())
            decision = result.get("decision", "allow")
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        # Server nicht erreichbar oder Fehler → allow (Claude nie haengen lassen)
        return

    if decision == "block":
        # Claude Code Hook-Protokoll: JSON auf stdout mit decision=block
        print(json.dumps({
            "decision": "block",
            "reason": "Blocked by user via Telegram",
        }))
        # Kein sys.exit noetig — Claude liest stdout


if __name__ == "__main__":
    main()
