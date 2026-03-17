# event_formatter.py
"""Smart-Level Event-Formatter fuer Telegram.
Kompakte Status-Nachricht mit live Updates: Thinking-Summary, Tool-Call-Einzeiler.
Alle Ausgaben als HTML (Telegram ParseMode.HTML).
"""

import html
import os
import re
import time
from typing import Callable, Optional

from claude_runner import RunEvent, EventType, split_for_telegram


def markdown_to_telegram_html(text: str) -> str:
    """Konvertiert Claude's Markdown-Output in Telegram-taugliches HTML."""
    try:
        # 1. HTML-Entities escapen (MUSS zuerst passieren)
        text = html.escape(text)

        # 2. Code-Bloecke (```lang\n...\n```) → <pre>
        text = re.sub(r'```\w*\n(.*?)```', r'<pre>\1</pre>', text, flags=re.DOTALL)

        # 3. Inline-Code (`...`) → <code>
        text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

        # 4. Bold (**text**) → <b>
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)

        # 5. Italic (*text*) → <i>  (nicht innerhalb von <b>)
        text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)

        # 6. Italic (_text_) → <i>  (nicht mitten in Woertern)
        text = re.sub(r'(?<![a-zA-Z0-9])_(.+?)_(?![a-zA-Z0-9])', r'<i>\1</i>', text)

        # 7. Links [text](url) → <a>
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

        # 8. Markdown-Header (### Text) → <b>Text</b> mit Newline
        text = re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)

        return text
    except Exception:
        return html.escape(text)

EDIT_INTERVAL = 1.5
MAX_THINKING_PREVIEW = 100
MAX_TOOL_INPUT_PREVIEW = 60
MAX_VISIBLE_TOOLS = 6
MAX_ANSWER_BUFFER = 50000


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


def _shorten_path(path: str) -> str:
    """Kuerzt lange Dateipfade auf die letzten 2 Segmente."""
    home = os.path.expanduser("~")
    if path.startswith(home):
        path = "~" + path[len(home):]
    parts = path.rstrip("/").split("/")
    if len(parts) > 3:
        return "/".join(parts[-2:])
    return path


class EventFormatter:
    """Empfaengt RunEvents und steuert Telegram-Anzeige im Smart-Level Format.

    Smart-Level:
    - Status-Nachricht: wird laufend editiert (Thinking, Tool-Calls, Fehler, Fertig)
    - Antwort-Nachrichten: separater Kanal fuer Text-Content
    - Tool-Gruppierung: gleiche aufeinanderfolgende Tools werden zusammengefasst
    """

    def __init__(self, send_fn: Callable, edit_fn: Callable):
        self._send = send_fn
        self._edit = edit_fn
        self._status_msg = None
        self._status_lines: list[str] = []
        self._tool_history: list[tuple[str, str]] = []  # (tool_name, detail)
        self._answer_msg = None
        self._answer_buffer = ""
        self._last_edit = 0.0

    async def handle_event(self, event: RunEvent) -> None:
        if event.type == EventType.THINKING:
            preview = event.content[:MAX_THINKING_PREVIEW]
            if len(event.content) > MAX_THINKING_PREVIEW:
                preview += "..."
            self._status_lines = [f"💭 <i>{html.escape(preview)}</i>"]
            self._tool_history.clear()
            await self._flush_status(force=True)

        elif event.type == EventType.TOOL_USE:
            detail = self._format_tool_detail(event)
            self._tool_history.append((event.tool_name, detail))
            self._rebuild_status_lines()
            await self._flush_status(force=True)

        elif event.type == EventType.TOOL_RESULT:
            if event.is_error:
                self._status_lines.append(f"❌ Fehler: {html.escape(event.content[:100])}")
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

    def _rebuild_status_lines(self) -> None:
        """Baut Status-Zeilen aus Tool-History mit Gruppierung auf."""
        if not self._tool_history:
            return

        # Gruppen bilden: aufeinanderfolgende gleiche Tools zusammenfassen
        groups: list[tuple[str, list[str]]] = []
        for tool_name, detail in self._tool_history:
            if groups and groups[-1][0] == tool_name:
                groups[-1][1].append(detail)
            else:
                groups.append((tool_name, [detail]))

        # Thinking-Zeile beibehalten falls vorhanden
        thinking_line = ""
        if self._status_lines and self._status_lines[0].startswith("💭"):
            thinking_line = self._status_lines[0]

        lines: list[str] = []
        if thinking_line:
            lines.append(thinking_line)

        for tool_name, details in groups:
            icon = TOOL_ICONS.get(tool_name, "🔧")
            if len(details) == 1:
                lines.append(f"{icon} <b>{html.escape(tool_name)}</b>: {html.escape(details[0])}")
            else:
                last = details[-1]
                lines.append(f"{icon} <b>{html.escape(tool_name)}</b> x{len(details)}: {html.escape(last)}")

        # Nur die letzten MAX_VISIBLE_TOOLS Zeilen anzeigen (+ Thinking)
        if thinking_line and len(lines) > MAX_VISIBLE_TOOLS + 1:
            hidden = len(lines) - MAX_VISIBLE_TOOLS - 1
            lines = [lines[0], f"<i>... +{hidden} weitere</i>"] + lines[-(MAX_VISIBLE_TOOLS):]
        elif not thinking_line and len(lines) > MAX_VISIBLE_TOOLS:
            hidden = len(lines) - MAX_VISIBLE_TOOLS
            lines = [f"<i>... +{hidden} weitere</i>"] + lines[-(MAX_VISIBLE_TOOLS):]

        self._status_lines = lines

    def _format_tool_detail(self, event: RunEvent) -> str:
        inp = event.tool_input
        if event.tool_name in ("Read", "Write", "Edit"):
            path = inp.get("file_path", str(inp))
            return _shorten_path(path)
        elif event.tool_name == "Bash":
            cmd = inp.get("command", str(inp))[:MAX_TOOL_INPUT_PREVIEW]
            return cmd
        elif event.tool_name == "Grep":
            pattern = inp.get("pattern", "")
            path = _shorten_path(inp.get("path", "."))
            return f"'{pattern}' in {path}"
        elif event.tool_name == "Glob":
            return inp.get("pattern", str(inp))[:MAX_TOOL_INPUT_PREVIEW]
        elif event.tool_name == "Agent":
            desc = inp.get("description", inp.get("prompt", str(inp)))[:MAX_TOOL_INPUT_PREVIEW]
            return desc
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
                # Stale message recovery: edit failed, send new message instead
                self._status_msg = None
                try:
                    self._status_msg = await self._send(text)
                except Exception:
                    pass

    async def _flush_answer(self, force: bool = False) -> None:
        if not self._answer_buffer.strip():
            return
        now = time.monotonic()
        if not force and now - self._last_edit < EDIT_INTERVAL:
            return
        self._last_edit = now
        # Truncate from the beginning if buffer exceeds max size
        if len(self._answer_buffer) > MAX_ANSWER_BUFFER:
            self._answer_buffer = self._answer_buffer[-MAX_ANSWER_BUFFER:]
        formatted = markdown_to_telegram_html(self._answer_buffer)
        chunks = split_for_telegram(formatted)
        if self._answer_msg is None:
            self._answer_msg = await self._send(chunks[0])
            for extra in chunks[1:]:
                self._answer_msg = await self._send(extra)
        else:
            try:
                await self._edit(self._answer_msg, chunks[0])
            except Exception:
                # Stale message recovery: edit failed, send new message instead
                self._answer_msg = None
                try:
                    self._answer_msg = await self._send(chunks[0])
                except Exception:
                    pass
            for extra in chunks[1:]:
                self._answer_msg = await self._send(extra)
