# Claude Code Telegram — Full Transparency + Interactive Permissions

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den Telegram Bot von einem Text-only Wrapper zu einem vollständigen Claude Code Frontend erweitern — mit Echtzeit-Transparenz (Thinking, Tool-Calls, Pläne) und interaktiver Permission-Kontrolle über Inline-Buttons.

**Architecture:** CLI + Hooks Ansatz. Claude CLI bleibt das Arbeitspferd (behält CLAUDE.md, Skills, MCP, Worktrees). Zwei parallele Kanäle: (1) stream-json stdout → Event-Parsing → Smart-Level Telegram-Anzeige (2) PreToolUse Hook → HTTP → Telegram Inline-Button → Permission Decision.

**Tech Stack:** Python 3.12, python-telegram-bot 22.x, asyncio (stdlib only, keine neuen Dependencies), Claude CLI (stream-json), Claude Code Hooks (PreToolUse)

**Agent Team:** Opus (Chef, delegiert nur) → 3x Sonnet parallel (Tasks 1-3) → Sonnet sequenziell (Task 4 Integration) → Haiku (Task 5 Docs)

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `event_formatter.py` | RunEvents → Telegram-Nachrichten (Smart-Level: kompakte Status-Msg, Thinking-Summary, Tool-Call-Einzeiler) |
| `permission_server.py` | Async HTTP Server (localhost:7429) für Hook-Callbacks + Permission-Queue + Timeout-Management |
| `hooks/pre_tool_use.py` | Executable Hook-Script: liest stdin (Tool-Info), POST an Permission-Server, wartet auf Response, gibt Decision auf stdout |
| `tests/test_event_formatter.py` | Unit Tests Event-Formatierung |
| `tests/test_permission_server.py` | Unit Tests Permission-Server + Tool-Kategorisierung |

### Modified Files

| File | Changes |
|------|---------|
| `claude_runner.py` | Event-Parsing erweitern (thinking, tool_use, tool_result), `RunEvent` Dataclass, `on_event` Callback statt `on_chunk` |
| `bot.py` | CallbackQuery Handler für Permission-Buttons, EventFormatter statt OutputStreamer, Permission-Server Lifecycle |
| `.env.example` | `PERMISSION_SERVER_PORT` |
| `CLAUDE.md` | Architektur-Update |

---

## Task 1: Event-System (parallel — Agent 1, Sonnet)

### RunEvent Dataclass + erweiterter Event-Parser

**Files:**
- Modify: `claude_runner.py`
- Modify: `tests/test_claude_runner.py`

**Context:** Aktuell filtert `_collect()` (Zeile 140-177) nur `event_type == "assistant"` mit `block.type == "text"`. Alle anderen Block-Typen (thinking, tool_use, tool_result) werden ignoriert. Die `run()` Methode akzeptiert `on_chunk: Callable` die nur Text-Strings empfängt. Wir erweitern das zu `on_event: Callable` die strukturierte `RunEvent` Objekte empfängt.

- [ ] **Step 1: RunEvent Dataclass definieren**

Am Anfang von `claude_runner.py`, nach den Imports:

```python
from dataclasses import dataclass, field
from enum import Enum

class EventType(Enum):
    THINKING = "thinking"
    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    RESULT = "result"

@dataclass
class RunEvent:
    type: EventType
    content: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_call_id: str = ""
    is_error: bool = False
    session_id: str = ""
    usage: dict = field(default_factory=dict)
```

- [ ] **Step 2: Failing Tests schreiben**

In `tests/test_claude_runner.py` — neue Tests fuer alle Event-Typen:

```python
import asyncio
import json
import pytest
from claude_runner import RunEvent, EventType

# Helper: simuliert stream-json Lines und sammelt Events
async def parse_lines(lines: list[str]) -> list[RunEvent]:
    """Parst stream-json Lines ueber ClaudeRunner._parse_event()."""
    from claude_runner import ClaudeRunner
    events = []
    runner = ClaudeRunner()
    for line in lines:
        parsed = runner._parse_line(line)
        if parsed:
            events.append(parsed)
    return events

def test_parse_thinking_block():
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "thinking", "thinking": "Ich ueberlege mir die Struktur..."}
    ]}})
    events = asyncio.get_event_loop().run_until_complete(parse_lines([line]))
    assert len(events) == 1
    assert events[0].type == EventType.THINKING
    assert "ueberlege" in events[0].content

def test_parse_text_block():
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Hier ist die Antwort."}
    ]}})
    events = asyncio.get_event_loop().run_until_complete(parse_lines([line]))
    assert len(events) == 1
    assert events[0].type == EventType.TEXT
    assert events[0].content == "Hier ist die Antwort."

def test_parse_tool_use_block():
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "toolu_123", "name": "Read",
         "input": {"file_path": "/tmp/test.py"}}
    ]}})
    events = asyncio.get_event_loop().run_until_complete(parse_lines([line]))
    assert len(events) == 1
    assert events[0].type == EventType.TOOL_USE
    assert events[0].tool_name == "Read"
    assert events[0].tool_input["file_path"] == "/tmp/test.py"
    assert events[0].tool_call_id == "toolu_123"

def test_parse_tool_result_block():
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "toolu_123",
         "content": "file contents here", "is_error": False}
    ]}})
    events = asyncio.get_event_loop().run_until_complete(parse_lines([line]))
    assert len(events) == 1
    assert events[0].type == EventType.TOOL_RESULT
    assert events[0].tool_call_id == "toolu_123"

def test_parse_result_event():
    line = json.dumps({"type": "result", "session_id": "sess_abc",
                       "usage": {"input_tokens": 100, "output_tokens": 50}})
    events = asyncio.get_event_loop().run_until_complete(parse_lines([line]))
    assert len(events) == 1
    assert events[0].type == EventType.RESULT
    assert events[0].session_id == "sess_abc"

def test_parse_mixed_blocks():
    """Ein assistant-Event mit mehreren Blocks erzeugt mehrere RunEvents."""
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "thinking", "thinking": "Denke nach..."},
        {"type": "text", "text": "Antwort"},
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
    ]}})
    events = asyncio.get_event_loop().run_until_complete(parse_lines([line]))
    assert len(events) == 3
    assert [e.type for e in events] == [EventType.THINKING, EventType.TEXT, EventType.TOOL_USE]

def test_parse_invalid_json():
    """Nicht-JSON Lines werden als TEXT Events behandelt."""
    events = asyncio.get_event_loop().run_until_complete(parse_lines(["not json"]))
    assert len(events) == 1
    assert events[0].type == EventType.TEXT
```

- [ ] **Step 3: Run tests — verify they FAIL**

Run: `cd /Users/hendrikgrueger/Coding/4_claude/remote-control-telegram && .venv/bin/pytest tests/test_claude_runner.py -v`
Expected: FAIL — `_parse_line` method does not exist yet

- [ ] **Step 4: Implement _parse_line() and refactor _collect()**

Add `_parse_line()` method to `ClaudeRunner`:

```python
def _parse_line(self, line: str) -> list[RunEvent]:
    """Parst eine stream-json Zeile in RunEvent(s)."""
    line = line.strip()
    if not line:
        return []
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return [RunEvent(type=EventType.TEXT, content=line + "\n")]

    events = []
    event_type = event.get("type", "")

    if event_type == "assistant":
        for block in event.get("message", {}).get("content", []):
            block_type = block.get("type", "")
            if block_type == "thinking":
                events.append(RunEvent(
                    type=EventType.THINKING,
                    content=block.get("thinking", ""),
                ))
            elif block_type == "text":
                events.append(RunEvent(
                    type=EventType.TEXT,
                    content=block.get("text", ""),
                ))
            elif block_type == "tool_use":
                events.append(RunEvent(
                    type=EventType.TOOL_USE,
                    tool_name=block.get("name", ""),
                    tool_input=block.get("input", {}),
                    tool_call_id=block.get("id", ""),
                ))
            elif block_type == "tool_result":
                events.append(RunEvent(
                    type=EventType.TOOL_RESULT,
                    content=str(block.get("content", "")),
                    tool_call_id=block.get("tool_use_id", ""),
                    is_error=block.get("is_error", False),
                ))
    elif event_type == "result":
        usage = event.get("usage", {})
        if usage:
            last_usage.clear()
            last_usage.update(usage)
            session_usage["input_tokens"] += usage.get("input_tokens", 0)
            session_usage["output_tokens"] += usage.get("output_tokens", 0)
            session_usage["requests"] += 1
        events.append(RunEvent(
            type=EventType.RESULT,
            session_id=event.get("session_id", ""),
            usage=usage,
        ))
    return events
```

Refactor `_collect()` to use `_parse_line()` and call `on_event` instead of `on_chunk`:

```python
async def _collect(self, on_event: Callable):
    assert self._process is not None
    new_session_id = None
    stderr_chunks = []

    async def read_stderr():
        async for line in self._process.stderr:
            stderr_chunks.append(line.decode("utf-8", errors="replace"))

    async def read_stdout():
        nonlocal new_session_id
        async for line in self._process.stdout:
            decoded = line.decode("utf-8", errors="replace").strip()
            if not decoded:
                continue
            for event in self._parse_line(decoded):
                if event.type == EventType.RESULT and event.session_id:
                    new_session_id = event.session_id
                await on_event(event)

    await asyncio.gather(read_stdout(), read_stderr())
    return_code = await self._process.wait()
    return new_session_id, "".join(stderr_chunks), return_code
```

Update `run()` signature: rename `on_chunk` → `on_event`:

```python
async def run(
    self,
    prompt: str,
    directory: str,
    session_id: Optional[str],
    on_event: Callable,   # CHANGED from on_chunk
    model: Optional[str] = None,
) -> Optional[str]:
```

- [ ] **Step 5: Run tests — verify they PASS**

Run: `.venv/bin/pytest tests/test_claude_runner.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add claude_runner.py tests/test_claude_runner.py
git commit -m "feat: RunEvent Dataclass + vollstaendiger Event-Parser (thinking, tool_use, tool_result)"
```

---

## Task 2: Smart-Level Event-Formatter (parallel — Agent 2, Sonnet)

### EventFormatter fuer Telegram

**Files:**
- Create: `event_formatter.py`
- Create: `tests/test_event_formatter.py`

**Context:** Der Formatter empfaengt `RunEvent` Objekte und steuert die Telegram-Anzeige im Smart-Level Format:
- **Thinking:** Erste ~100 Zeichen als kursive Zusammenfassung in Status-Nachricht
- **Tool-Calls:** Einzeiler mit Icon in laufender Status-Nachricht: `📖 Read: src/foo.py`
- **Tool-Results:** Nur bei Fehler anzeigen
- **Text:** Normaler Antwort-Text als eigene Nachricht(n)
- **Result:** Status-Nachricht mit "Fertig" abschliessen

Die Status-Nachricht wird laufend editiert (eine einzige Nachricht die sich aktualisiert).

**Dependency:** Benoetigt `RunEvent` und `EventType` aus `claude_runner.py` (Task 1). Da parallel: importiere die Dataclass-Definition direkt, oder definiere sie inline fuer Tests. Bei Integration werden die Imports zusammengefuehrt.

- [ ] **Step 1: EventType und RunEvent inline fuer Tests definieren**

Da Task 1 parallel laeuft, definiere die Dataclasses im Test-File inline (wird bei Integration ersetzt durch Import):

```python
# tests/test_event_formatter.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass, field
from enum import Enum

# Inline-Definition (wird bei Integration durch Import ersetzt)
class EventType(Enum):
    THINKING = "thinking"
    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    RESULT = "result"

@dataclass
class RunEvent:
    type: EventType
    content: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_call_id: str = ""
    is_error: bool = False
    session_id: str = ""
    usage: dict = field(default_factory=dict)
```

- [ ] **Step 2: Failing Tests schreiben**

```python
@pytest.mark.asyncio
async def test_thinking_creates_status_msg():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(
        type=EventType.THINKING,
        content="Ich muss zuerst die Dateistruktur analysieren und dann den besten Ansatz waehlen",
    ))
    send.assert_called_once()
    call_text = send.call_args[0][0]
    assert "Ich muss zuerst" in call_text
    assert len(call_text) <= 120  # Truncated

@pytest.mark.asyncio
async def test_tool_use_appends_to_status():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(type=EventType.TOOL_USE, tool_name="Read",
                                     tool_input={"file_path": "/src/main.py"}))
    # Erste Tool-Call erstellt Status-Msg
    assert send.called
    call_text = send.call_args[0][0]
    assert "Read" in call_text
    assert "/src/main.py" in call_text

@pytest.mark.asyncio
async def test_multiple_tools_grouped_in_one_status():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(type=EventType.TOOL_USE, tool_name="Read",
                                     tool_input={"file_path": "a.py"}))
    await fmt.handle_event(RunEvent(type=EventType.TOOL_USE, tool_name="Grep",
                                     tool_input={"pattern": "foo"}))

    # Zweiter Tool-Call editiert bestehende Status-Msg
    assert edit.called
    edit_text = edit.call_args[0][1]
    assert "Read" in edit_text
    assert "Grep" in edit_text

@pytest.mark.asyncio
async def test_text_sends_new_message():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(type=EventType.TEXT, content="Die Antwort lautet 42."))
    await fmt.finalize()
    assert send.called

@pytest.mark.asyncio
async def test_tool_result_error_shown():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(type=EventType.TOOL_RESULT, is_error=True,
                                     content="File not found"))
    # Fehler wird in Status angezeigt
    text = send.call_args[0][0] if send.called else edit.call_args[0][1]
    assert "Fehler" in text or "❌" in text

@pytest.mark.asyncio
async def test_result_finalizes_status():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(type=EventType.TOOL_USE, tool_name="Read",
                                     tool_input={"file_path": "x.py"}))
    await fmt.handle_event(RunEvent(type=EventType.RESULT, session_id="s1"))

    # Status-Msg sollte "Fertig" enthalten
    last_edit_text = edit.call_args[0][1]
    assert "✅" in last_edit_text or "Fertig" in last_edit_text

@pytest.mark.asyncio
async def test_bash_command_shown_as_code():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(type=EventType.TOOL_USE, tool_name="Bash",
                                     tool_input={"command": "git status"}))
    text = send.call_args[0][0]
    assert "git status" in text
```

- [ ] **Step 3: Run tests — verify they FAIL**

Run: `.venv/bin/pytest tests/test_event_formatter.py -v`
Expected: FAIL — EventFormatter not defined

- [ ] **Step 4: Implement event_formatter.py**

```python
# event_formatter.py
"""Smart-Level Event-Formatter fuer Telegram.
Kompakte Status-Nachricht mit live Updates."""

import time
from typing import Callable, Optional

# Import bei Integration: from claude_runner import RunEvent, EventType, split_for_telegram
# Waehrend paralleler Entwicklung: inline Definition (wird bei Integration ersetzt)
from dataclasses import dataclass, field
from enum import Enum

class EventType(Enum):
    THINKING = "thinking"
    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    RESULT = "result"

@dataclass
class RunEvent:
    type: EventType
    content: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_call_id: str = ""
    is_error: bool = False
    session_id: str = ""
    usage: dict = field(default_factory=dict)


EDIT_INTERVAL = 1.5
MAX_THINKING_PREVIEW = 100
MAX_TOOL_INPUT_PREVIEW = 60
MAX_MSG_LEN = 4096

TOOL_ICONS = {
    "Read": "📖", "Write": "✏️", "Edit": "✏️",
    "Bash": "💻", "Grep": "🔍", "Glob": "📂",
    "Agent": "🤖", "WebSearch": "🌐", "WebFetch": "🌐",
}


def split_for_telegram(text: str, max_len: int = MAX_MSG_LEN) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while len(text) > max_len:
        split_at = text.rfind("\n", 0, max_len)
        if split_at <= 0:
            split_at = max_len
        else:
            split_at += 1
        chunks.append(text[:split_at])
        text = text[split_at:]
    if text:
        chunks.append(text)
    return chunks


class EventFormatter:
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
            await self._flush_status()

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
```

- [ ] **Step 5: Run tests — verify they PASS**

Run: `.venv/bin/pytest tests/test_event_formatter.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add event_formatter.py tests/test_event_formatter.py
git commit -m "feat: Smart-Level EventFormatter — kompakte Status-Msg mit Thinking/Tool-Call Anzeige"
```

---

## Task 3: Permission-System (parallel — Agent 3, Sonnet)

### Permission-Server + Hook-Script

**Files:**
- Create: `permission_server.py`
- Create: `hooks/pre_tool_use.py`
- Create: `tests/test_permission_server.py`

**Context:** Der Permission-Server ist ein asyncio TCP Server auf localhost der HTTP-Requests vom Hook-Script empfaengt. Tool-Kategorien bestimmen das Verhalten:

| Kategorie | Tools | Verhalten |
|-----------|-------|-----------|
| HARMLESS | Read, Grep, Glob, Bash(ls/git status/echo) | Auto-accept, kein Button |
| MODIFYING | Write, Edit, Bash(allgemein) | Telegram-Button, 60s Timeout → auto-accept |
| DESTRUCTIVE | Bash(rm/git push/git reset) | Telegram-Button, KEIN Timeout, wartet ewig |

**Flow:**
1. Claude CLI ruft PreToolUse Hook auf
2. `hooks/pre_tool_use.py` liest Tool-Info von stdin, POST an localhost:7429
3. `permission_server.py` kategorisiert Tool, zeigt ggf. Telegram-Button via Callback
4. User klickt Button (oder Timeout)
5. Server sendet HTTP Response mit `{"decision": "allow"}` oder `{"decision": "block"}`
6. Hook gibt Decision auf stdout aus

- [ ] **Step 1: Failing Tests fuer Tool-Kategorisierung**

```python
# tests/test_permission_server.py
import asyncio
import json
import pytest
from permission_server import categorize_tool, ToolCategory, PermissionServer, PermissionRequest

def test_read_is_harmless():
    assert categorize_tool("Read", {}) == ToolCategory.HARMLESS

def test_grep_is_harmless():
    assert categorize_tool("Grep", {"pattern": "foo"}) == ToolCategory.HARMLESS

def test_glob_is_harmless():
    assert categorize_tool("Glob", {"pattern": "*.py"}) == ToolCategory.HARMLESS

def test_write_is_modifying():
    assert categorize_tool("Write", {"file_path": "/tmp/x"}) == ToolCategory.MODIFYING

def test_edit_is_modifying():
    assert categorize_tool("Edit", {"file_path": "/tmp/x"}) == ToolCategory.MODIFYING

def test_bash_ls_is_harmless():
    assert categorize_tool("Bash", {"command": "ls -la"}) == ToolCategory.HARMLESS

def test_bash_git_status_is_harmless():
    assert categorize_tool("Bash", {"command": "git status"}) == ToolCategory.HARMLESS

def test_bash_echo_is_harmless():
    assert categorize_tool("Bash", {"command": "echo hello"}) == ToolCategory.HARMLESS

def test_bash_generic_is_modifying():
    assert categorize_tool("Bash", {"command": "python3 script.py"}) == ToolCategory.MODIFYING

def test_bash_rm_is_destructive():
    assert categorize_tool("Bash", {"command": "rm -rf /tmp/foo"}) == ToolCategory.DESTRUCTIVE

def test_bash_rm_single_is_destructive():
    assert categorize_tool("Bash", {"command": "rm file.txt"}) == ToolCategory.DESTRUCTIVE

def test_bash_git_push_is_destructive():
    assert categorize_tool("Bash", {"command": "git push --force origin main"}) == ToolCategory.DESTRUCTIVE

def test_bash_git_push_simple_is_destructive():
    assert categorize_tool("Bash", {"command": "git push"}) == ToolCategory.DESTRUCTIVE

def test_bash_git_reset_is_destructive():
    assert categorize_tool("Bash", {"command": "git reset --hard"}) == ToolCategory.DESTRUCTIVE

def test_bash_trash_is_destructive():
    assert categorize_tool("Bash", {"command": "trash old_file.py"}) == ToolCategory.DESTRUCTIVE

def test_unknown_tool_is_modifying():
    assert categorize_tool("SomeNewTool", {}) == ToolCategory.MODIFYING
```

- [ ] **Step 2: Run tests — verify they FAIL**

Run: `.venv/bin/pytest tests/test_permission_server.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement permission_server.py**

```python
# permission_server.py
"""Permission-Server: asyncio HTTP Server fuer Hook-Callbacks + Telegram-Button-Management."""

import asyncio
import json
import logging
import os
import re
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_PORT = int(os.getenv("PERMISSION_SERVER_PORT", "7429"))


class ToolCategory(Enum):
    HARMLESS = "harmless"
    MODIFYING = "modifying"
    DESTRUCTIVE = "destructive"


HARMLESS_BASH = re.compile(
    r"^\s*(ls|cat|head|tail|echo|pwd|whoami|date|wc|"
    r"git\s+(status|log|diff|branch|show|rev-parse)|"
    r"find|tree|which|type|file|stat|du|df|uname|id|env|printenv)\b"
)

DESTRUCTIVE_BASH = re.compile(
    r"(rm\s|rm$|rmdir|"
    r"git\s+(push|reset|clean|checkout\s+\.|restore\s+\.)|"
    r"trash|kill|pkill|killall|"
    r"DROP\s|DELETE\s|TRUNCATE\s)"
)

HARMLESS_TOOLS = {"Read", "Grep", "Glob", "Agent"}
MODIFYING_TOOLS = {"Write", "Edit", "NotebookEdit"}

TIMEOUTS = {
    ToolCategory.HARMLESS: 0,
    ToolCategory.MODIFYING: 60,
    ToolCategory.DESTRUCTIVE: 0,  # 0 = wartet ewig
}


def categorize_tool(tool_name: str, tool_input: dict) -> ToolCategory:
    if tool_name in HARMLESS_TOOLS:
        return ToolCategory.HARMLESS
    if tool_name in MODIFYING_TOOLS:
        return ToolCategory.MODIFYING
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if DESTRUCTIVE_BASH.search(cmd):
            return ToolCategory.DESTRUCTIVE
        if HARMLESS_BASH.match(cmd):
            return ToolCategory.HARMLESS
        return ToolCategory.MODIFYING
    return ToolCategory.MODIFYING


class PermissionRequest:
    def __init__(self, request_id: str, tool_name: str, tool_input: dict, category: ToolCategory):
        self.request_id = request_id
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.category = category
        self.decision: Optional[str] = None
        self.event = asyncio.Event()


class PermissionServer:
    def __init__(self, port: int = DEFAULT_PORT, on_permission_request: Optional[Callable] = None):
        self._port = port
        self._server: Optional[asyncio.Server] = None
        self._pending: dict[str, PermissionRequest] = {}
        self._on_permission_request = on_permission_request
        self._request_counter = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection, "127.0.0.1", self._port
        )
        logger.info("Permission-Server gestartet auf Port %d", self._port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for req in self._pending.values():
            req.decision = "allow"
            req.event.set()

    def resolve(self, request_id: str, decision: str) -> bool:
        req = self._pending.get(request_id)
        if not req:
            return False
        req.decision = decision
        req.event.set()
        return True

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            data = await asyncio.wait_for(reader.read(65536), timeout=5.0)
            request_text = data.decode("utf-8", errors="replace")

            body_start = request_text.find("\r\n\r\n")
            if body_start == -1:
                self._send_response(writer, 400, {"decision": "allow"})
                return

            body = request_text[body_start + 4:]
            tool_info = json.loads(body)

            tool_name = tool_info.get("tool_name", "unknown")
            tool_input = tool_info.get("tool_input", {})
            category = categorize_tool(tool_name, tool_input)

            if category == ToolCategory.HARMLESS:
                self._send_response(writer, 200, {"decision": "allow"})
                return

            self._request_counter += 1
            request_id = f"perm_{self._request_counter}"
            req = PermissionRequest(request_id, tool_name, tool_input, category)
            self._pending[request_id] = req

            if self._on_permission_request:
                await self._on_permission_request(req)

            timeout = TIMEOUTS[category]
            try:
                if timeout > 0:
                    await asyncio.wait_for(req.event.wait(), timeout=timeout)
                else:
                    await req.event.wait()
            except asyncio.TimeoutError:
                req.decision = "allow"

            decision = req.decision or "allow"
            self._pending.pop(request_id, None)

            block_decision = "allow" if decision == "allow" else "block"
            self._send_response(writer, 200, {"decision": block_decision})

        except Exception as e:
            logger.error("Permission-Server Fehler: %s", e)
            self._send_response(writer, 200, {"decision": "allow"})
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    def _send_response(self, writer, status: int, body: dict):
        response_body = json.dumps(body)
        http = (
            f"HTTP/1.1 {status} OK\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(response_body)}\r\n"
            f"\r\n"
            f"{response_body}"
        )
        writer.write(http.encode())
```

- [ ] **Step 4: Tests fuer Permission-Server (async)**

Append to `tests/test_permission_server.py`:

```python
@pytest.mark.asyncio
async def test_server_auto_accepts_harmless():
    server = PermissionServer(port=17429)
    await server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", 17429)
        body = json.dumps({"tool_name": "Read", "tool_input": {}})
        request = f"POST / HTTP/1.1\r\nContent-Length: {len(body)}\r\n\r\n{body}"
        writer.write(request.encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(4096), timeout=5)
        response = data.decode()
        assert '"allow"' in response
        writer.close()
    finally:
        await server.stop()

@pytest.mark.asyncio
async def test_server_requests_permission_for_write():
    received_requests = []

    async def on_request(req):
        received_requests.append(req)
        req.decision = "allow"
        req.event.set()

    server = PermissionServer(port=17430, on_permission_request=on_request)
    await server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", 17430)
        body = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "/tmp/x"}})
        request = f"POST / HTTP/1.1\r\nContent-Length: {len(body)}\r\n\r\n{body}"
        writer.write(request.encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(4096), timeout=5)
        response = data.decode()
        assert '"allow"' in response
        assert len(received_requests) == 1
        assert received_requests[0].tool_name == "Write"
        writer.close()
    finally:
        await server.stop()

@pytest.mark.asyncio
async def test_server_blocks_when_denied():
    async def on_request(req):
        req.decision = "block"
        req.event.set()

    server = PermissionServer(port=17431, on_permission_request=on_request)
    await server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", 17431)
        body = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}})
        request = f"POST / HTTP/1.1\r\nContent-Length: {len(body)}\r\n\r\n{body}"
        writer.write(request.encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(4096), timeout=5)
        response = data.decode()
        assert '"block"' in response
        writer.close()
    finally:
        await server.stop()

@pytest.mark.asyncio
async def test_resolve_returns_false_for_unknown_id():
    server = PermissionServer(port=17432)
    assert server.resolve("nonexistent", "allow") is False
```

- [ ] **Step 5: Run tests — verify they PASS**

Run: `.venv/bin/pytest tests/test_permission_server.py -v`
Expected: ALL PASS

- [ ] **Step 6: Create hooks/pre_tool_use.py**

```python
#!/usr/bin/env python3
# hooks/pre_tool_use.py
"""Claude Code PreToolUse Hook.
Liest Tool-Info von stdin, POST an Permission-Server, gibt Decision auf stdout."""

import json
import os
import sys
import urllib.request

PERMISSION_SERVER_PORT = os.getenv("PERMISSION_SERVER_PORT", "7429")
PERMISSION_SERVER_URL = f"http://127.0.0.1:{PERMISSION_SERVER_PORT}"


def main():
    try:
        tool_info = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return  # Kein Input → allow (default)

    data = json.dumps({
        "tool_name": tool_info.get("tool_name", "unknown"),
        "tool_input": tool_info.get("tool_input", {}),
    }).encode()

    req = urllib.request.Request(
        PERMISSION_SERVER_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read())
            decision = result.get("decision", "allow")
    except Exception:
        return  # Bei Fehler → allow (kein Output = default allow)

    if decision == "block":
        print(json.dumps({
            "decision": "block",
            "reason": "Blocked by user via Telegram",
        }))


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Make hook executable + Commit**

```bash
mkdir -p hooks
chmod +x hooks/pre_tool_use.py
git add permission_server.py hooks/pre_tool_use.py tests/test_permission_server.py
git commit -m "feat: Permission-System — HTTP Server + Hook Script + Tool-Kategorisierung"
```

---

## Task 4: Integration in bot.py (sequenziell — Agent 4, Sonnet, wartet auf Tasks 1-3)

### bot.py umbauen + CallbackQuery Handler

**Files:**
- Modify: `bot.py`
- Modify: `.env.example`

**Context:** Alle drei Module zusammenfuehren:
1. `claude_runner.py` liefert jetzt `RunEvent` statt Text-Chunks
2. `event_formatter.py` formatiert Events fuer Telegram
3. `permission_server.py` zeigt Inline-Buttons fuer Permissions
4. `bot.py` muss: EventFormatter statt OutputStreamer nutzen, Permission-Server starten/stoppen, CallbackQuery Handler registrieren

**WICHTIG bei Integration:**
- `event_formatter.py` hat aktuell inline EventType/RunEvent Definitionen → durch Import aus `claude_runner.py` ersetzen
- `OutputStreamer` in `claude_runner.py` kann entfernt oder als Legacy beibehalten werden
- `on_chunk` → `on_event` in `handle_message`

- [ ] **Step 1: event_formatter.py — Inline-Definitionen durch Imports ersetzen**

Entferne die inline `EventType`, `RunEvent`, `split_for_telegram` Definitionen und ersetze durch:

```python
from claude_runner import RunEvent, EventType, split_for_telegram
```

- [ ] **Step 2: Neue Imports in bot.py**

```python
import json
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
from event_formatter import EventFormatter
from permission_server import PermissionServer, ToolCategory
from claude_runner import RunEvent, EventType
```

- [ ] **Step 3: Permission-Server Instanz + Callback**

Nach den globalen State-Variablen:

```python
PERMISSION_PORT = int(os.getenv("PERMISSION_SERVER_PORT", "7429"))
perm_server = PermissionServer(port=PERMISSION_PORT)

# Wird spaeter mit app.bot verbunden
_bot_instance = None

async def on_permission_request(req):
    """Wird vom PermissionServer aufgerufen — zeigt Telegram Inline-Keyboard."""
    if not _bot_instance:
        req.decision = "allow"
        req.event.set()
        return

    icon = "🛑" if req.category == ToolCategory.DESTRUCTIVE else "⚠️"
    timeout_info = ""
    if req.category == ToolCategory.MODIFYING:
        timeout_info = "\n⏱ _Auto-accept in 60s_"
    elif req.category == ToolCategory.DESTRUCTIVE:
        timeout_info = "\n🛑 _Wartet auf deine Entscheidung_"

    detail = json.dumps(req.tool_input, indent=2, ensure_ascii=False)
    if len(detail) > 500:
        detail = detail[:500] + "..."

    text = (
        f"{icon} *Permission: {req.tool_name}*\n"
        f"```\n{detail}\n```"
        f"{timeout_info}"
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Erlauben", callback_data=f"perm:allow:{req.request_id}"),
        InlineKeyboardButton("❌ Blockieren", callback_data=f"perm:block:{req.request_id}"),
    ]])

    await _bot_instance.send_message(
        chat_id=ALLOWED_USER_ID,
        text=text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )
```

- [ ] **Step 4: CallbackQuery Handler**

```python
async def handle_permission_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verarbeitet Permission-Button Clicks."""
    query = update.callback_query
    if not query or not query.data:
        return
    if update.effective_user and update.effective_user.id != ALLOWED_USER_ID:
        await query.answer("Nicht autorisiert.")
        return

    await query.answer()

    parts = query.data.split(":", 2)
    if len(parts) != 3 or parts[0] != "perm":
        return

    action = parts[1]    # "allow" oder "block"
    request_id = parts[2]  # "perm_N"

    decision = "allow" if action == "allow" else "block"
    resolved = perm_server.resolve(request_id, decision)

    if resolved:
        emoji = "✅ Erlaubt" if decision == "allow" else "❌ Blockiert"
        await query.edit_message_text(emoji)
    else:
        await query.edit_message_text("⚠️ Request bereits beantwortet")
```

- [ ] **Step 5: handle_message umbauen**

Ersetze den `OutputStreamer`-basierten Code durch `EventFormatter`:

```python
@authorized_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if runner.is_busy():
        await update.message.reply_text("⏳ Claude arbeitet noch. Mit /stop abbrechen.")
        return

    text = update.message.text
    if len(text) > MAX_MESSAGE_LEN:
        await update.message.reply_text(f"Nachricht zu lang ({len(text)}/{MAX_MESSAGE_LEN} Zeichen).")
        return

    ws = ws_manager.get_active()
    session_id = ws.get("session_id")

    if ws_manager.get_plan_mode():
        text = f"Erstelle einen detaillierten Plan fuer folgende Aufgabe. Implementiere NICHTS, plane nur:\n\n{text}"

    async def send_fn(content: str):
        return await update.message.reply_text(content)

    async def edit_fn(msg, content: str):
        try:
            await msg.edit_text(content)
        except Exception:
            pass

    formatter = EventFormatter(send_fn=send_fn, edit_fn=edit_fn)

    try:
        new_session_id = await runner.run(
            prompt=text,
            directory=ws["directory"],
            session_id=session_id,
            on_event=formatter.handle_event,
            model=ws_manager.get_model(),
        )
        await formatter.finalize()

        if new_session_id:
            ws_manager.set_session_id(new_session_id)

    except SessionExpiredError:
        ws_manager.clear_session_id()
        await update.message.reply_text(
            "⚠️ Session abgelaufen — neues Gespraech gestartet. Bitte nochmal senden."
        )
    except asyncio.TimeoutError:
        await update.message.reply_text(
            f"⏱ Timeout nach {os.getenv('CLAUDE_TIMEOUT_SECONDS', '300')}s. "
            "Mit /stop bereinigen und nochmal versuchen."
        )
    except Exception as e:
        logger.error("Unbehandelter Fehler: %s", e, exc_info=True)
        await update.message.reply_text("Ein Fehler ist aufgetreten. Details im Log.")
```

- [ ] **Step 6: main() erweitern**

```python
def main():
    global _bot_instance

    app = Application.builder().token(TOKEN).build()
    _bot_instance = app.bot

    # Permission-Server Callback setzen
    perm_server._on_permission_request = on_permission_request

    # Commands
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("ws", cmd_ws))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("compact", cmd_compact))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("rename", cmd_rename))
    app.add_handler(CommandHandler("usage", cmd_usage))
    app.add_handler(CommandHandler("skills", cmd_skills))

    # Permission-Buttons (VOR dem Message Handler!)
    app.add_handler(CallbackQueryHandler(handle_permission_callback))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Permission-Server lifecycle
    async def post_init(application):
        await perm_server.start()

    async def post_shutdown(application):
        await perm_server.stop()

    app.post_init = post_init
    app.post_shutdown = post_shutdown

    logger.info("Bot gestartet. Workspace: %s", ws_manager.get_active_name())
    app.run_polling(allowed_updates=["message", "callback_query"])
```

- [ ] **Step 7: .env.example updaten**

Append:
```
# Permission-Server Port (Hook kommuniziert hierueber)
PERMISSION_SERVER_PORT=7429
```

- [ ] **Step 8: /help Text updaten**

Permission-Info hinzufuegen:
```python
"*Permissions:*\n"
"Claude fragt bei Write/Edit/Bash um Erlaubnis via Button.\n"
"Harmlose Tools (Read/Grep) laufen automatisch.\n\n"
```

- [ ] **Step 9: Run all tests**

Run: `.venv/bin/pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 10: Commit**

```bash
git add bot.py .env.example
git commit -m "feat: Integration — EventFormatter + Permission-Server + CallbackQuery Handler"
```

---

## Task 5: Hook-Installation + Finalisierung (sequenziell — Agent 5, Haiku)

### Hook registrieren, Docs updaten, Smoke Test

**Files:**
- Modify: `CLAUDE.md`
- Modify: `install.sh`

- [ ] **Step 1: Hook in Claude Code Hooks registrieren**

Der Hook muss in den Claude Code Settings registriert werden. Pruefen ob `~/.claude/settings.json` existiert und den Hook hinzufuegen:

```bash
# Pruefen ob settings.json existiert
cat ~/.claude/settings.json 2>/dev/null || echo "{}"
```

Hook-Konfiguration (in `~/.claude/settings.json` unter `hooks`):
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "command": "/Users/hendrikgrueger/Coding/4_claude/remote-control-telegram/hooks/pre_tool_use.py"
      }
    ]
  }
}
```

**WICHTIG:** Bestehende settings.json Inhalte NICHT ueberschreiben! Hook zur bestehenden Konfiguration HINZUFUEGEN.

- [ ] **Step 2: install.sh erweitern**

Hook-Registrierung am Ende von install.sh hinzufuegen:

```bash
# Hook registrieren
HOOK_PATH="$INSTALL_DIR/hooks/pre_tool_use.py"
SETTINGS_FILE="$HOME/.claude/settings.json"
if [ -f "$SETTINGS_FILE" ]; then
    echo "⚠️  Bitte Hook manuell in $SETTINGS_FILE registrieren:"
    echo "    PreToolUse → $HOOK_PATH"
else
    echo "Claude Code Settings nicht gefunden."
    echo "Nach Installation: Hook in ~/.claude/settings.json registrieren"
fi
```

- [ ] **Step 3: CLAUDE.md updaten**

Architektur-Tabelle aktualisieren:
```markdown
| `event_formatter.py` | Smart-Level Event-Anzeige (Thinking, Tool-Calls, Ergebnisse) |
| `permission_server.py` | HTTP Server fuer interaktive Permission-Kontrolle via Telegram-Buttons |
| `hooks/pre_tool_use.py` | Claude Code PreToolUse Hook — leitet Tool-Calls an Permission-Server |
```

Neuen Abschnitt "Permission-System" hinzufuegen:
```markdown
## Permission-System

Tool-Calls werden in 3 Kategorien eingeteilt:
- **Harmlos** (Read, Grep, Glob): Automatisch erlaubt
- **Modifizierend** (Write, Edit, Bash): Button in Telegram, 60s Timeout → auto-accept
- **Destruktiv** (rm, git push): Button in Telegram, KEIN Timeout, wartet auf Entscheidung

Der Permission-Server laeuft auf localhost:7429 (konfigurierbar via PERMISSION_SERVER_PORT).
```

- [ ] **Step 4: /help Command aktualisieren mit Permission-Info**

Pruefen ob der Help-Text die neuen Features beschreibt.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md install.sh
git commit -m "docs: Hook-Installation + Permission-System Dokumentation"
```

- [ ] **Step 6: Bot neu starten und Smoke Test**

```bash
launchctl kickstart -k gui/$(id -u)/com.claude-telegram-remote.bot
```

Manueller Smoke Test:
1. Nachricht an Bot senden → Status-Msg mit Thinking/Tool-Calls sichtbar?
2. Claude fuehrt Read aus → kein Button (harmlos)?
3. Claude fuehrt Write aus → Permission-Button erscheint?
4. Button klicken → Claude faehrt fort?
5. Timeout abwarten → Auto-accept?

---

## Agent Team Uebersicht

```
                    ┌──────────────┐
                    │  Opus (Chef) │
                    │  Delegiert   │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────▼─────┐ ┌───▼────┐ ┌─────▼──────┐
        │  Agent 1   │ │ Agent 2│ │  Agent 3   │
        │  Sonnet    │ │ Sonnet │ │  Sonnet    │
        │  Event-    │ │ Event- │ │ Permission │
        │  Parser    │ │Formatt.│ │  System    │
        └─────┬──────┘ └───┬────┘ └─────┬──────┘
              │            │            │
              └────────────┼────────────┘
                           │
                    ┌──────▼───────┐
                    │   Agent 4    │
                    │   Sonnet     │
                    │ Integration  │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │   Agent 5    │
                    │   Haiku      │
                    │ Docs + Hook  │
                    └──────────────┘
```

**Parallelisierung:** Tasks 1, 2, 3 sind vollstaendig unabhaengig.
**Sequenziell:** Task 4 wartet auf 1+2+3. Task 5 wartet auf 4.
