# event_formatter.py
"""Smart-Level Event-Formatter fuer Telegram.
Kompakte Status-Nachricht mit live Updates: Thinking-Summary, Tool-Call-Einzeiler.
"""

import time
from typing import Callable, Optional

from claude_runner import RunEvent, EventType, split_for_telegram

EDIT_INTERVAL = 1.5
MAX_THINKING_PREVIEW = 100
MAX_TOOL_INPUT_PREVIEW = 60

TOOL_ICONS = {
    "Read": "📖",
    "Write": "✏️",
    "Edit": "✏️",
    "Bash": "💻",
    "Grep": "🔍",
    "Glob": "📂",
    "Agent": "🤖",
    "WebSearch": "🌐",
    "WebFetch": "🌐",
}


class EventFormatter:
    """Empfaengt RunEvents und steuert Telegram-Anzeige im Smart-Level Format.

    Smart-Level:
    - Status-Nachricht: wird laufend editiert (Thinking, Tool-Calls, Fehler, Fertig)
    - Antwort-Nachrichten: separater Kanal fuer Text-Content
    """

    def __init__(self, send_fn: Callable, edit_fn: Callable):
        self._send = send_fn
        self._edit = edit_fn
        self._status_msg = None
        self._status_lines: list[str] = []
        self._answer_msg = None
        self._answer_buffer = ""
        self._last_edit = 0.0

    async def handle_event(self, event: RunEvent) -> None:
        if event.type == EventType.THINKING:
            preview = event.content[:MAX_THINKING_PREVIEW]
            if len(event.content) > MAX_THINKING_PREVIEW:
                preview += "..."
            self._status_lines = [f"💭 _{preview}_"]
            await self._flush_status(force=True)

        elif event.type == EventType.TOOL_USE:
            icon = TOOL_ICONS.get(event.tool_name, "🔧")
            detail = self._format_tool_detail(event)
            self._status_lines.append(f"{icon} {event.tool_name}: {detail}")
            await self._flush_status(force=True)

        elif event.type == EventType.TOOL_RESULT:
            if event.is_error:
                self._status_lines.append(f"❌ Fehler: {event.content[:100]}")
                await self._flush_status(force=True)

        elif event.type == EventType.TEXT:
            self._answer_buffer += event.content
            now = time.monotonic()
            if now - self._last_edit >= EDIT_INTERVAL:
                await self._flush_answer()

        elif event.type == EventType.RESULT:
            await self._flush_answer(force=True)
            if self._status_msg and self._status_lines:
                self._status_lines.append("✅ Fertig")
                await self._flush_status(force=True)

    async def finalize(self) -> None:
        """Flush ausstehende Antwort-Puffer."""
        await self._flush_answer(force=True)

    def _format_tool_detail(self, event: RunEvent) -> str:
        inp = event.tool_input
        if event.tool_name in ("Read", "Write", "Edit"):
            return inp.get("file_path", str(inp))[:MAX_TOOL_INPUT_PREVIEW]
        elif event.tool_name == "Bash":
            cmd = inp.get("command", str(inp))[:MAX_TOOL_INPUT_PREVIEW]
            return f"`{cmd}`"
        elif event.tool_name == "Grep":
            return f"'{inp.get('pattern', '')}' in {inp.get('path', '.')}"
        elif event.tool_name == "Glob":
            return inp.get("pattern", str(inp))[:MAX_TOOL_INPUT_PREVIEW]
        return str(inp)[:MAX_TOOL_INPUT_PREVIEW]

    async def _flush_status(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_edit < EDIT_INTERVAL:
            return
        self._last_edit = now
        text = "\n".join(self._status_lines)
        if not text.strip():
            return
        if self._status_msg is None:
            self._status_msg = await self._send(text)
        else:
            try:
                await self._edit(self._status_msg, text)
            except Exception:
                pass

    async def _flush_answer(self, force: bool = False) -> None:
        if not self._answer_buffer.strip():
            return
        self._last_edit = time.monotonic()
        chunks = split_for_telegram(self._answer_buffer)
        if self._answer_msg is None:
            self._answer_msg = await self._send(chunks[0])
            for extra in chunks[1:]:
                self._answer_msg = await self._send(extra)
        else:
            try:
                await self._edit(self._answer_msg, chunks[0])
            except Exception:
                pass
            for extra in chunks[1:]:
                self._answer_msg = await self._send(extra)
