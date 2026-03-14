# tests/test_event_formatter.py
"""Unit Tests fuer EventFormatter — Smart-Level Telegram-Anzeige."""

import pytest
from unittest.mock import AsyncMock, MagicMock

# TODO: Bei Integration durch Import ersetzen: from claude_runner import RunEvent, EventType, split_for_telegram
# Inline-Definition (wird bei Integration durch Import ersetzt)
from event_formatter import EventFormatter, EventType, RunEvent


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
async def test_thinking_truncates_long_content():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    long_content = "x" * 200
    await fmt.handle_event(RunEvent(type=EventType.THINKING, content=long_content))
    call_text = send.call_args[0][0]
    assert "..." in call_text


@pytest.mark.asyncio
async def test_tool_use_appends_to_status():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(
        type=EventType.TOOL_USE,
        tool_name="Read",
        tool_input={"file_path": "/src/main.py"},
    ))
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

    await fmt.handle_event(RunEvent(
        type=EventType.TOOL_USE,
        tool_name="Read",
        tool_input={"file_path": "a.py"},
    ))
    await fmt.handle_event(RunEvent(
        type=EventType.TOOL_USE,
        tool_name="Grep",
        tool_input={"pattern": "foo", "path": "."},
    ))

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

    await fmt.handle_event(RunEvent(
        type=EventType.TOOL_RESULT,
        is_error=True,
        content="File not found",
    ))
    # Fehler wird in Status angezeigt
    text = send.call_args[0][0] if send.called else edit.call_args[0][1]
    assert "Fehler" in text or "❌" in text


@pytest.mark.asyncio
async def test_tool_result_no_error_not_shown():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(
        type=EventType.TOOL_RESULT,
        is_error=False,
        content="Some file content",
    ))
    send.assert_not_called()
    edit.assert_not_called()


@pytest.mark.asyncio
async def test_result_finalizes_status():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(
        type=EventType.TOOL_USE,
        tool_name="Read",
        tool_input={"file_path": "x.py"},
    ))
    await fmt.handle_event(RunEvent(type=EventType.RESULT, session_id="s1"))

    # Status-Msg sollte "Fertig" enthalten
    last_edit_text = edit.call_args[0][1]
    assert "✅" in last_edit_text or "Fertig" in last_edit_text


@pytest.mark.asyncio
async def test_bash_command_shown_as_code():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(
        type=EventType.TOOL_USE,
        tool_name="Bash",
        tool_input={"command": "git status"},
    ))
    text = send.call_args[0][0]
    assert "git status" in text


@pytest.mark.asyncio
async def test_tool_icons_read():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(
        type=EventType.TOOL_USE,
        tool_name="Read",
        tool_input={"file_path": "foo.py"},
    ))
    text = send.call_args[0][0]
    assert "📖" in text


@pytest.mark.asyncio
async def test_tool_icons_grep():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(
        type=EventType.TOOL_USE,
        tool_name="Grep",
        tool_input={"pattern": "test"},
    ))
    text = send.call_args[0][0]
    assert "🔍" in text


@pytest.mark.asyncio
async def test_tool_icons_bash():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(
        type=EventType.TOOL_USE,
        tool_name="Bash",
        tool_input={"command": "ls"},
    ))
    text = send.call_args[0][0]
    assert "💻" in text


@pytest.mark.asyncio
async def test_unknown_tool_uses_default_icon():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(
        type=EventType.TOOL_USE,
        tool_name="UnknownTool",
        tool_input={},
    ))
    text = send.call_args[0][0]
    assert "🔧" in text


@pytest.mark.asyncio
async def test_thinking_uses_italic_format():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(
        type=EventType.THINKING,
        content="Analysiere den Code",
    ))
    text = send.call_args[0][0]
    assert "💭" in text
    assert "<i>" in text  # HTML Kursiv-Formatierung


@pytest.mark.asyncio
async def test_grep_format_shows_pattern_and_path():
    send = AsyncMock(return_value=MagicMock(message_id=1))
    edit = AsyncMock()
    fmt = EventFormatter(send_fn=send, edit_fn=edit)

    await fmt.handle_event(RunEvent(
        type=EventType.TOOL_USE,
        tool_name="Grep",
        tool_input={"pattern": "myFunc", "path": "src/"},
    ))
    text = send.call_args[0][0]
    assert "myFunc" in text
    assert "src/" in text
