"""Permission-Server: asyncio HTTP Server fuer Hook-Callbacks + Permission-Queue + Timeout-Management.

Empfaengt PreToolUse Hook-Requests von hooks/pre_tool_use.py,
kategorisiert Tools und koordiniert Telegram-Button-Permission-Flow.

Port: localhost:7429 (konfigurierbar via PERMISSION_SERVER_PORT env var)
"""

import asyncio
import json
import logging
import os
import re
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_PORT = int(os.getenv("PERMISSION_SERVER_PORT", "7429"))


# ---------------------------------------------------------------------------
# Tool-Kategorien
# ---------------------------------------------------------------------------

class ToolCategory(Enum):
    HARMLESS = "harmless"
    MODIFYING = "modifying"
    DESTRUCTIVE = "destructive"


# Bash-Commands die IMMER harmlos sind (kein Schreiben, kein Loeschen)
_HARMLESS_BASH = re.compile(
    r"^\s*("
    r"ls(\s|$)|"
    r"cat(\s|$)|"
    r"head(\s|$)|"
    r"tail(\s|$)|"
    r"echo(\s|$)|"
    r"pwd(\s|$)|"
    r"whoami(\s|$)|"
    r"date(\s|$)|"
    r"wc(\s|$)|"
    r"which(\s|$)|"
    r"type(\s|$)|"
    r"file(\s|$)|"
    r"stat(\s|$)|"
    r"du(\s|$)|"
    r"df(\s|$)|"
    r"uname(\s|$)|"
    r"id(\s|$)|"
    r"env(\s|$)|"
    r"printenv(\s|$)|"
    r"find(\s|$)|"
    r"tree(\s|$)|"
    r"git\s+(status|log|diff|branch|show|rev-parse)(\s|$)"
    r")"
)

# Bash-Commands die IMMER destruktiv sind (irreversibel loeschen/ueberschreiben)
_DESTRUCTIVE_BASH = re.compile(
    r"(^|\s|;|&&|\|)"
    r"("
    r"rm(\s|$)|"
    r"rmdir(\s|$)|"
    r"git\s+push(\s|$)|"
    r"git\s+reset(\s|$)|"
    r"git\s+clean(\s|$)|"
    r"git\s+checkout\s+\.|"
    r"git\s+restore\s+\.|"
    r"trash(\s|$)|"
    r"kill(\s|$)|"
    r"pkill(\s|$)|"
    r"killall(\s|$)|"
    r"DROP\s|"
    r"DELETE\s|"
    r"TRUNCATE\s"
    r")"
)

# Tools die per se harmlos sind (nur lesend)
_HARMLESS_TOOLS = frozenset({"Read", "Grep", "Glob", "Agent"})

# Tools die modifizierend sind (schreiben, aber reversibel)
_MODIFYING_TOOLS = frozenset({"Write", "Edit", "NotebookEdit"})

# Timeout pro Kategorie (Sekunden; 0 = wartet ewig)
TIMEOUTS: dict[ToolCategory, int] = {
    ToolCategory.HARMLESS: 0,       # auto-accept, kein Wait
    ToolCategory.MODIFYING: 60,     # 60s → auto-accept
    ToolCategory.DESTRUCTIVE: 0,    # wartet ewig auf User-Entscheidung
}


def categorize_tool(tool_name: str, tool_input: dict) -> ToolCategory:
    """Kategorisiert ein Tool anhand Name + Input in HARMLESS / MODIFYING / DESTRUCTIVE."""
    if tool_name in _HARMLESS_TOOLS:
        return ToolCategory.HARMLESS
    if tool_name in _MODIFYING_TOOLS:
        return ToolCategory.MODIFYING
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if _DESTRUCTIVE_BASH.search(cmd):
            return ToolCategory.DESTRUCTIVE
        if _HARMLESS_BASH.match(cmd):
            return ToolCategory.HARMLESS
        return ToolCategory.MODIFYING
    # Unbekannte Tools konservativ als MODIFYING behandeln
    return ToolCategory.MODIFYING


# ---------------------------------------------------------------------------
# Permission-Request Datenklasse
# ---------------------------------------------------------------------------

class PermissionRequest:
    """Repraesentiert eine ausstehende Erlaubnis-Anfrage fuer einen Tool-Call."""

    def __init__(
        self,
        request_id: str,
        tool_name: str,
        tool_input: dict,
        category: ToolCategory,
    ):
        self.request_id = request_id
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.category = category
        self.decision: Optional[str] = None
        self.event = asyncio.Event()

    def __repr__(self) -> str:
        return (
            f"PermissionRequest(id={self.request_id!r}, tool={self.tool_name!r}, "
            f"category={self.category.value}, decision={self.decision!r})"
        )


# ---------------------------------------------------------------------------
# Permission-Server
# ---------------------------------------------------------------------------

class PermissionServer:
    """Asyncio TCP Server fuer PreToolUse Hook-Callbacks.

    Flow:
      1. Hook sendet POST mit {tool_name, tool_input}
      2. Server kategorisiert Tool
      3. Bei HARMLESS: sofort allow
      4. Bei MODIFYING/DESTRUCTIVE: on_permission_request Callback → wartet auf Event
      5. Bei Timeout (MODIFYING) → auto-allow
      6. Bei DESTRUCTIVE → wartet ewig
      7. Sendet HTTP Response mit {decision: "allow" | "block"}
    """

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        on_permission_request: Optional[Callable] = None,
    ):
        self._port = port
        self._server: Optional[asyncio.Server] = None
        self._pending: dict[str, PermissionRequest] = {}
        self._on_permission_request = on_permission_request
        self._request_counter = 0

    async def start(self) -> None:
        """Startet den TCP-Server."""
        self._server = await asyncio.start_server(
            self._handle_connection, "127.0.0.1", self._port
        )
        logger.info("Permission-Server gestartet auf Port %d", self._port)

    async def stop(self) -> None:
        """Stoppt den Server und loest alle ausstehenden Requests mit 'allow' auf."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        # Alle haengenden Requests freigeben damit Claude nicht blockiert
        for req in list(self._pending.values()):
            req.decision = "allow"
            req.event.set()
        self._pending.clear()

    def resolve(self, request_id: str, decision: str) -> bool:
        """Loest eine ausstehende Permission-Anfrage auf (z.B. via Telegram-Button).

        Returns:
            True wenn Request gefunden und aufgeloest, False wenn unbekannte ID.
        """
        req = self._pending.get(request_id)
        if not req:
            return False
        req.decision = decision
        req.event.set()
        return True

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Verarbeitet eine eingehende TCP-Verbindung."""
        try:
            # Lese HTTP-Request (max 64 KB)
            data = await asyncio.wait_for(reader.read(65536), timeout=5.0)
            request_text = data.decode("utf-8", errors="replace")

            # HTTP-Body nach dem Header extrahieren
            body_start = request_text.find("\r\n\r\n")
            if body_start == -1:
                self._send_response(writer, 400, {"decision": "allow"})
                return

            body = request_text[body_start + 4:]
            try:
                tool_info = json.loads(body)
            except json.JSONDecodeError:
                self._send_response(writer, 400, {"decision": "allow"})
                return

            tool_name = tool_info.get("tool_name", "unknown")
            tool_input = tool_info.get("tool_input", {})
            category = categorize_tool(tool_name, tool_input)

            # HARMLESS → sofort allow, kein Callback noetig
            if category == ToolCategory.HARMLESS:
                self._send_response(writer, 200, {"decision": "allow"})
                return

            # MODIFYING / DESTRUCTIVE → Permission-Request erstellen
            self._request_counter += 1
            request_id = f"perm_{self._request_counter}"
            req = PermissionRequest(request_id, tool_name, tool_input, category)
            self._pending[request_id] = req

            # Callback benachrichtigen (z.B. Telegram-Button senden)
            if self._on_permission_request:
                try:
                    await self._on_permission_request(req)
                except Exception as e:
                    logger.error("on_permission_request Callback Fehler: %s", e)

            # Auf Entscheidung warten
            timeout = TIMEOUTS[category]
            try:
                if timeout > 0:
                    await asyncio.wait_for(req.event.wait(), timeout=float(timeout))
                else:
                    # Kein Timeout: wartet ewig (DESTRUCTIVE) oder sofort fuer HARMLESS (nicht erreichbar)
                    await req.event.wait()
            except asyncio.TimeoutError:
                # MODIFYING Timeout → auto-accept
                req.decision = "allow"
                logger.info("Timeout fuer %s %s → auto-allow", tool_name, request_id)

            decision = req.decision or "allow"
            self._pending.pop(request_id, None)

            block_decision = "allow" if decision == "allow" else "block"
            self._send_response(writer, 200, {"decision": block_decision})

        except Exception as e:
            logger.error("Permission-Server Fehler bei Connection-Handling: %s", e)
            # Bei jedem Fehler → allow, damit Claude nie haengt
            try:
                self._send_response(writer, 200, {"decision": "allow"})
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    def _send_response(self, writer: asyncio.StreamWriter, status: int, body: dict) -> None:
        """Sendet eine HTTP-Response."""
        response_body = json.dumps(body)
        http = (
            f"HTTP/1.1 {status} OK\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(response_body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
            f"{response_body}"
        )
        writer.write(http.encode())
