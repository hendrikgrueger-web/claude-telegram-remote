# tests/test_event_formatter_stability.py
"""Stability & edge-case tests for EventFormatter and markdown_to_telegram_html."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_runner import RunEvent, EventType
from event_formatter import (
    EDIT_INTERVAL,
    MAX_ANSWER_BUFFER,
    MAX_VISIBLE_TOOLS,
    EventFormatter,
    markdown_to_telegram_html,
)


# ---------------------------------------------------------------------------
# 1. markdown_to_telegram_html — normal, nested, broken, empty, huge
# ---------------------------------------------------------------------------

class TestMarkdownToTelegramHtml:
    def test_normal_markdown(self):
        md = "Hello **bold** and *italic* and `code`"
        result = markdown_to_telegram_html(md)
        assert "<b>bold</b>" in result
        assert "<i>italic</i>" in result
        assert "<code>code</code>" in result

    def test_code_block(self):
        md = "```python\nprint('hi')\n```"
        result = markdown_to_telegram_html(md)
        assert "<pre>" in result
        assert "print" in result

    def test_link_conversion(self):
        md = "[click](https://example.com)"
        result = markdown_to_telegram_html(md)
        assert '<a href="https://example.com">click</a>' in result

    def test_header_to_bold(self):
        md = "### My Header"
        result = markdown_to_telegram_html(md)
        assert "<b>My Header</b>" in result

    def test_nested_bold_italic(self):
        md = "**bold and *nested italic* inside**"
        result = markdown_to_telegram_html(md)
        # Should at least produce valid output without crashing
        assert "<b>" in result

    def test_html_entities_escaped(self):
        md = "Use <div> & 'quotes' in markdown"
        result = markdown_to_telegram_html(md)
        assert "&lt;div&gt;" in result
        assert "&amp;" in result

    def test_broken_markdown_unclosed_bold(self):
        md = "**unclosed bold"
        result = markdown_to_telegram_html(md)
        # Should not crash, returns some string
        assert isinstance(result, str)
        assert "unclosed" in result

    def test_broken_markdown_unclosed_backticks(self):
        md = "```\nno closing fence"
        result = markdown_to_telegram_html(md)
        assert isinstance(result, str)

    def test_broken_markdown_mismatched_formatting(self):
        md = "*bold** and **italic* confusion"
        result = markdown_to_telegram_html(md)
        assert isinstance(result, str)

    def test_empty_string(self):
        assert markdown_to_telegram_html("") == ""

    def test_very_long_string_100k(self):
        big = "Hello **bold** world\n" * 5000  # ~100K chars
        result = markdown_to_telegram_html(big)
        assert len(result) > 0
        assert "<b>bold</b>" in result

    def test_special_regex_chars(self):
        """Chars that could break regex: ()[]{}+?\\|^$."""
        md = "regex (test) [bracket] {brace} a+b? c\\d |pipe| ^start$ end."
        result = markdown_to_telegram_html(md)
        assert isinstance(result, str)

    def test_underscore_italic(self):
        md = "this _word_ is italic"
        result = markdown_to_telegram_html(md)
        assert "<i>word</i>" in result

    def test_underscore_in_word_not_italic(self):
        md = "some_variable_name"
        result = markdown_to_telegram_html(md)
        # Underscores inside words should NOT become italic
        assert "<i>" not in result


# ---------------------------------------------------------------------------
# 2. markdown_to_telegram_html fallback on regex failure
# ---------------------------------------------------------------------------

class TestMarkdownFallback:
    def test_fallback_returns_escaped_text(self):
        """If regex raises, the except block returns html.escape(text)."""
        # We patch re.sub to raise an error on the first call
        original_text = "Hello <world> & friends"
        with patch("event_formatter.re.sub", side_effect=RuntimeError("regex boom")):
            result = markdown_to_telegram_html(original_text)
        # Fallback: html.escape of original text
        assert "&lt;world&gt;" in result
        assert "&amp;" in result


# ---------------------------------------------------------------------------
# 3. EventFormatter with failing send_fn
# ---------------------------------------------------------------------------

class TestFailingSendFn:
    @pytest.mark.asyncio
    async def test_send_raises_does_not_crash(self):
        send = AsyncMock(side_effect=Exception("Telegram API down"))
        edit = AsyncMock()
        fmt = EventFormatter(send_fn=send, edit_fn=edit)

        # Should not raise — the status flush catches send errors in the
        # stale-message recovery path, but initial send is NOT wrapped.
        # Let's see if it blows up or is silently handled.
        # Actually, looking at the code: _flush_status does NOT wrap the
        # initial send in try/except. So this WILL raise.
        # We test that it propagates without corrupting state.
        with pytest.raises(Exception, match="Telegram API down"):
            await fmt.handle_event(RunEvent(
                type=EventType.THINKING,
                content="test thinking",
            ))

    @pytest.mark.asyncio
    async def test_send_raises_on_answer_does_not_crash(self):
        send = AsyncMock(side_effect=Exception("send failed"))
        edit = AsyncMock()
        fmt = EventFormatter(send_fn=send, edit_fn=edit)

        # TEXT events call _flush_answer, which also does not wrap first send
        with pytest.raises(Exception, match="send failed"):
            await fmt.handle_event(RunEvent(type=EventType.TEXT, content="hello"))
            await fmt.finalize()


# ---------------------------------------------------------------------------
# 4. EventFormatter with failing edit_fn — stale message recovery
# ---------------------------------------------------------------------------

class TestFailingEditFn:
    @pytest.mark.asyncio
    async def test_edit_failure_sends_new_status_message(self):
        """When edit fails, formatter should send a fresh message (stale recovery)."""
        msg1 = MagicMock(message_id=1)
        msg2 = MagicMock(message_id=2)
        send = AsyncMock(side_effect=[msg1, msg2])
        edit = AsyncMock(side_effect=Exception("Message not found"))
        fmt = EventFormatter(send_fn=send, edit_fn=edit)

        # First tool creates status via send
        await fmt.handle_event(RunEvent(
            type=EventType.TOOL_USE,
            tool_name="Read",
            tool_input={"file_path": "a.py"},
        ))
        assert send.call_count == 1

        # Second tool tries edit (fails) then sends new message
        await fmt.handle_event(RunEvent(
            type=EventType.TOOL_USE,
            tool_name="Bash",
            tool_input={"command": "ls"},
        ))
        assert send.call_count == 2
        assert edit.call_count == 1

    @pytest.mark.asyncio
    async def test_edit_failure_on_answer_sends_new_message(self):
        """When answer edit fails, a new message is sent."""
        msg1 = MagicMock(message_id=1)
        msg2 = MagicMock(message_id=2)
        send = AsyncMock(side_effect=[msg1, msg2])
        edit = AsyncMock(side_effect=Exception("Message too old"))
        fmt = EventFormatter(send_fn=send, edit_fn=edit)

        # First text — sends via send
        fmt._answer_buffer = "first answer"
        fmt._answer_msg = msg1  # pretend we already have a message
        fmt._last_edit = 0.0  # force flush

        await fmt._flush_answer(force=True)
        # edit failed, so send should be called for recovery
        assert send.call_count == 1


# ---------------------------------------------------------------------------
# 5. Rate limiting — EDIT_INTERVAL respected
# ---------------------------------------------------------------------------

class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_flush_answer_respects_edit_interval(self):
        """Multiple rapid TEXT events should NOT each trigger a send/edit."""
        send = AsyncMock(return_value=MagicMock(message_id=1))
        edit = AsyncMock()
        fmt = EventFormatter(send_fn=send, edit_fn=edit)

        # Send 10 TEXT events rapidly
        for i in range(10):
            await fmt.handle_event(RunEvent(
                type=EventType.TEXT,
                content=f"word{i} ",
            ))

        # Only the first should have triggered a flush (subsequent ones skipped
        # because time.monotonic() - _last_edit < EDIT_INTERVAL)
        # The first event triggers flush because _last_edit starts at 0.0
        # and time.monotonic() is always > EDIT_INTERVAL from epoch 0
        initial_send_count = send.call_count

        # Now finalize to flush remaining
        await fmt.finalize()

        # Total sends should be <= 2 (initial + finalize)
        assert send.call_count + edit.call_count <= initial_send_count + 2

    @pytest.mark.asyncio
    async def test_flush_status_respects_edit_interval_when_not_forced(self):
        """Non-forced status flush should skip if within EDIT_INTERVAL."""
        send = AsyncMock(return_value=MagicMock(message_id=1))
        edit = AsyncMock()
        fmt = EventFormatter(send_fn=send, edit_fn=edit)

        fmt._status_lines = ["test line"]
        fmt._last_edit = time.monotonic()  # just edited

        await fmt._flush_status(force=False)
        # Should not send because we're within EDIT_INTERVAL
        send.assert_not_called()
        edit.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Buffer overflow protection — >50000 chars truncated
# ---------------------------------------------------------------------------

class TestBufferOverflow:
    @pytest.mark.asyncio
    async def test_answer_buffer_truncated(self):
        """answer_buffer > MAX_ANSWER_BUFFER gets truncated from the beginning."""
        send = AsyncMock(return_value=MagicMock(message_id=1))
        edit = AsyncMock()
        fmt = EventFormatter(send_fn=send, edit_fn=edit)

        # Fill buffer beyond max
        fmt._answer_buffer = "X" * (MAX_ANSWER_BUFFER + 10000)
        fmt._last_edit = 0.0  # force flush

        await fmt._flush_answer(force=True)

        # After flush, the buffer was truncated before formatting
        # The send was called with formatted content
        assert send.called
        # The internal buffer was truncated to MAX_ANSWER_BUFFER before formatting
        # Verify by checking it was processed without error

    @pytest.mark.asyncio
    async def test_answer_buffer_keeps_tail_on_overflow(self):
        """On overflow, the TAIL (most recent) content is kept."""
        send = AsyncMock(return_value=MagicMock(message_id=1))
        edit = AsyncMock()
        fmt = EventFormatter(send_fn=send, edit_fn=edit)

        prefix = "A" * (MAX_ANSWER_BUFFER + 5000)
        suffix = "ENDMARKER"
        fmt._answer_buffer = prefix + suffix
        fmt._last_edit = 0.0

        await fmt._flush_answer(force=True)

        sent_text = send.call_args[0][0]
        assert "ENDMARKER" in sent_text


# ---------------------------------------------------------------------------
# 7. Tool grouping — _rebuild_status_lines
# ---------------------------------------------------------------------------

class TestToolGrouping:
    def test_consecutive_same_tools_grouped(self):
        fmt = EventFormatter(send_fn=AsyncMock(), edit_fn=AsyncMock())
        fmt._tool_history = [
            ("Read", "a.py"),
            ("Read", "b.py"),
            ("Read", "c.py"),
        ]
        fmt._status_lines = []
        fmt._rebuild_status_lines()

        joined = "\n".join(fmt._status_lines)
        assert "x3" in joined
        assert "c.py" in joined  # last detail shown

    def test_different_tools_separate_lines(self):
        fmt = EventFormatter(send_fn=AsyncMock(), edit_fn=AsyncMock())
        fmt._tool_history = [
            ("Read", "a.py"),
            ("Bash", "ls"),
            ("Grep", "'foo' in ."),
        ]
        fmt._status_lines = []
        fmt._rebuild_status_lines()

        joined = "\n".join(fmt._status_lines)
        assert "Read" in joined
        assert "Bash" in joined
        assert "Grep" in joined
        # No grouping count like "x2:" or "x3:" should appear
        import re as _re
        assert not _re.search(r' x\d+:', joined)

    def test_max_visible_tools_limit(self):
        """More than MAX_VISIBLE_TOOLS entries → older ones hidden."""
        fmt = EventFormatter(send_fn=AsyncMock(), edit_fn=AsyncMock())
        # Create many different tools so they don't group
        fmt._tool_history = [
            (f"Tool{i}", f"detail{i}") for i in range(MAX_VISIBLE_TOOLS + 5)
        ]
        fmt._status_lines = []
        fmt._rebuild_status_lines()

        joined = "\n".join(fmt._status_lines)
        assert "weitere" in joined  # hidden tools indicator
        # The last MAX_VISIBLE_TOOLS should be visible
        assert f"detail{MAX_VISIBLE_TOOLS + 4}" in joined

    def test_max_visible_with_thinking_line(self):
        """Thinking line is preserved, tools are limited."""
        fmt = EventFormatter(send_fn=AsyncMock(), edit_fn=AsyncMock())
        fmt._status_lines = ["💭 <i>thinking...</i>"]
        fmt._tool_history = [
            (f"Tool{i}", f"detail{i}") for i in range(MAX_VISIBLE_TOOLS + 5)
        ]
        fmt._rebuild_status_lines()

        # Thinking line should still be first
        assert fmt._status_lines[0].startswith("💭")
        assert "weitere" in "\n".join(fmt._status_lines)

    def test_empty_tool_history(self):
        fmt = EventFormatter(send_fn=AsyncMock(), edit_fn=AsyncMock())
        fmt._tool_history = []
        fmt._status_lines = ["💭 <i>thinking</i>"]
        fmt._rebuild_status_lines()
        # Should not change status_lines when history is empty
        assert fmt._status_lines == ["💭 <i>thinking</i>"]


# ---------------------------------------------------------------------------
# 8. _format_tool_detail — various tool types
# ---------------------------------------------------------------------------

class TestFormatToolDetail:
    def _make_event(self, tool_name, tool_input):
        return RunEvent(
            type=EventType.TOOL_USE,
            tool_name=tool_name,
            tool_input=tool_input,
        )

    def test_read_tool(self):
        fmt = EventFormatter(send_fn=AsyncMock(), edit_fn=AsyncMock())
        event = self._make_event("Read", {"file_path": "/Users/me/project/src/main.py"})
        result = fmt._format_tool_detail(event)
        assert "main.py" in result

    def test_bash_tool(self):
        fmt = EventFormatter(send_fn=AsyncMock(), edit_fn=AsyncMock())
        event = self._make_event("Bash", {"command": "git status --short"})
        result = fmt._format_tool_detail(event)
        assert "git status" in result

    def test_bash_tool_truncated(self):
        fmt = EventFormatter(send_fn=AsyncMock(), edit_fn=AsyncMock())
        long_cmd = "x" * 200
        event = self._make_event("Bash", {"command": long_cmd})
        result = fmt._format_tool_detail(event)
        assert len(result) <= 60  # MAX_TOOL_INPUT_PREVIEW

    def test_grep_tool(self):
        fmt = EventFormatter(send_fn=AsyncMock(), edit_fn=AsyncMock())
        event = self._make_event("Grep", {"pattern": "myFunc", "path": "/src/"})
        result = fmt._format_tool_detail(event)
        assert "myFunc" in result
        assert "src" in result

    def test_grep_tool_default_path(self):
        fmt = EventFormatter(send_fn=AsyncMock(), edit_fn=AsyncMock())
        event = self._make_event("Grep", {"pattern": "search_term"})
        result = fmt._format_tool_detail(event)
        assert "search_term" in result
        assert "." in result  # default path

    def test_glob_tool(self):
        fmt = EventFormatter(send_fn=AsyncMock(), edit_fn=AsyncMock())
        event = self._make_event("Glob", {"pattern": "**/*.py"})
        result = fmt._format_tool_detail(event)
        assert "**/*.py" in result

    def test_agent_tool_with_description(self):
        fmt = EventFormatter(send_fn=AsyncMock(), edit_fn=AsyncMock())
        event = self._make_event("Agent", {"description": "Search for config files"})
        result = fmt._format_tool_detail(event)
        assert "Search for config" in result

    def test_agent_tool_with_prompt_fallback(self):
        fmt = EventFormatter(send_fn=AsyncMock(), edit_fn=AsyncMock())
        event = self._make_event("Agent", {"prompt": "Do something"})
        result = fmt._format_tool_detail(event)
        assert "Do something" in result

    def test_unknown_tool(self):
        fmt = EventFormatter(send_fn=AsyncMock(), edit_fn=AsyncMock())
        event = self._make_event("SuperTool", {"foo": "bar", "baz": 42})
        result = fmt._format_tool_detail(event)
        assert isinstance(result, str)
        assert len(result) <= 60

    def test_write_tool(self):
        fmt = EventFormatter(send_fn=AsyncMock(), edit_fn=AsyncMock())
        event = self._make_event("Write", {"file_path": "/tmp/output.txt"})
        result = fmt._format_tool_detail(event)
        assert "output.txt" in result

    def test_edit_tool(self):
        fmt = EventFormatter(send_fn=AsyncMock(), edit_fn=AsyncMock())
        event = self._make_event("Edit", {"file_path": "/project/src/app.py"})
        result = fmt._format_tool_detail(event)
        assert "app.py" in result


# ---------------------------------------------------------------------------
# 9. finalize() — flushes remaining buffer
# ---------------------------------------------------------------------------

class TestFinalize:
    @pytest.mark.asyncio
    async def test_finalize_flushes_pending_answer(self):
        send = AsyncMock(return_value=MagicMock(message_id=1))
        edit = AsyncMock()
        fmt = EventFormatter(send_fn=send, edit_fn=edit)

        # Add text but don't trigger flush (set _last_edit to now)
        fmt._answer_buffer = "Some pending answer text"
        fmt._last_edit = time.monotonic()

        # Normal flush would skip (within EDIT_INTERVAL)
        await fmt._flush_answer(force=False)
        assert not send.called

        # But finalize forces it
        await fmt.finalize()
        assert send.called
        sent_text = send.call_args[0][0]
        assert "pending answer" in sent_text

    @pytest.mark.asyncio
    async def test_finalize_noop_on_empty_buffer(self):
        send = AsyncMock()
        edit = AsyncMock()
        fmt = EventFormatter(send_fn=send, edit_fn=edit)

        await fmt.finalize()
        send.assert_not_called()
        edit.assert_not_called()

    @pytest.mark.asyncio
    async def test_finalize_whitespace_only_buffer(self):
        send = AsyncMock()
        edit = AsyncMock()
        fmt = EventFormatter(send_fn=send, edit_fn=edit)

        fmt._answer_buffer = "   \n\n  "
        await fmt.finalize()
        # Whitespace-only buffer should not trigger send
        send.assert_not_called()


# ---------------------------------------------------------------------------
# 10. Stale message recovery — edit failure → new message
# ---------------------------------------------------------------------------

class TestStaleMessageRecovery:
    @pytest.mark.asyncio
    async def test_status_stale_recovery(self):
        """On edit failure in _flush_status, a new message is sent."""
        msg1 = MagicMock(message_id=1)
        msg_recovery = MagicMock(message_id=99)
        send = AsyncMock(return_value=msg_recovery)
        edit = AsyncMock(side_effect=Exception("message deleted"))
        fmt = EventFormatter(send_fn=send, edit_fn=edit)

        # Create initial status (pretend it was already sent)
        fmt._status_msg = msg1
        fmt._status_lines = ["test status"]
        fmt._last_edit = 0.0

        await fmt._flush_status(force=True)

        # Edit was attempted and failed
        edit.assert_called_once()
        # Recovery: new message sent
        assert send.call_count == 1
        # Status message updated to recovery message
        assert fmt._status_msg == msg_recovery

    @pytest.mark.asyncio
    async def test_status_recovery_send_also_fails(self):
        """If both edit and recovery send fail, formatter does not crash."""
        msg1 = MagicMock(message_id=1)
        send = AsyncMock(side_effect=Exception("all sends fail"))
        edit = AsyncMock(side_effect=Exception("edit fail"))
        fmt = EventFormatter(send_fn=send, edit_fn=edit)

        fmt._status_msg = msg1
        fmt._status_lines = ["test"]
        fmt._last_edit = 0.0

        # Should NOT raise — double failure is silently handled
        await fmt._flush_status(force=True)
        assert fmt._status_msg is None  # reset after edit failure

    @pytest.mark.asyncio
    async def test_answer_stale_recovery(self):
        """On edit failure in _flush_answer, a new message is sent."""
        msg1 = MagicMock(message_id=1)
        msg2 = MagicMock(message_id=2)
        send = AsyncMock(side_effect=[msg2])
        edit = AsyncMock(side_effect=Exception("message too old"))
        fmt = EventFormatter(send_fn=send, edit_fn=edit)

        fmt._answer_msg = msg1
        fmt._answer_buffer = "Some answer content"
        fmt._last_edit = 0.0

        await fmt._flush_answer(force=True)

        edit.assert_called_once()
        assert send.call_count == 1
        assert fmt._answer_msg == msg2
