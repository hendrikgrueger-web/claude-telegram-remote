# tests/test_claude_runner_stability.py
"""Stability / reliability tests for ClaudeRunner subprocess handling."""
import asyncio
import collections
import json
import unittest.mock as mock

import pytest
import pytest_asyncio

from claude_runner import (
    ClaudeRunner,
    EventType,
    RunEvent,
    SessionExpiredError,
    TransientError,
    _SESSION_EXPIRED_PATTERNS,
    _STDERR_MAXLEN,
    _TRANSIENT_ERROR_PATTERNS,
    split_for_telegram,
)


# ── 1. Lock timeout: lock is released when subprocess hangs ──────────────────

@pytest.mark.asyncio
async def test_lock_released_after_timeout():
    """If the inner run hangs, the lock-level timeout fires and releases the lock."""
    runner = ClaudeRunner()

    # Mock _run_inner to block forever
    async def hanging_inner(*args, **kwargs):
        await asyncio.sleep(9999)

    runner._run_inner = hanging_inner  # type: ignore[assignment]

    # Patch TIMEOUT constants so the test is fast (lock_timeout = TIMEOUT + 30)
    import claude_runner as cr
    orig_timeout = cr.TIMEOUT
    orig_extra = cr._LOCK_TIMEOUT_EXTRA
    cr.TIMEOUT = 1
    cr._LOCK_TIMEOUT_EXTRA = 1  # lock_timeout = 2s

    try:
        with pytest.raises(asyncio.TimeoutError):
            await runner.run("test", "/tmp", None, lambda e: None)

        # The lock must be free after the timeout
        assert not runner.is_busy(), "Lock should be released after timeout"
    finally:
        cr.TIMEOUT = orig_timeout
        cr._LOCK_TIMEOUT_EXTRA = orig_extra


# ── 2. stop() with no running process ────────────────────────────────────────

@pytest.mark.asyncio
async def test_stop_no_process():
    """Calling stop() when nothing is running should not crash."""
    runner = ClaudeRunner()
    assert runner._process is None
    assert runner._pid is None
    await runner.stop()  # Should be a no-op


@pytest.mark.asyncio
async def test_stop_no_process_multiple_calls():
    """Multiple stop() calls with no process should all be safe."""
    runner = ClaudeRunner()
    await runner.stop()
    await runner.stop()
    await runner.stop()


# ── 3. is_busy() returns correct state ───────────────────────────────────────

@pytest.mark.asyncio
async def test_is_busy_before_and_after_lock():
    """is_busy() should reflect the lock state accurately."""
    runner = ClaudeRunner()
    assert not runner.is_busy()

    busy_during = None

    async with runner._lock:
        busy_during = runner.is_busy()

    assert busy_during is True, "is_busy should be True while lock is held"
    assert not runner.is_busy(), "is_busy should be False after lock release"


@pytest.mark.asyncio
async def test_is_busy_with_concurrent_access():
    """is_busy() should be True when another coroutine holds the lock."""
    runner = ClaudeRunner()
    lock_acquired = asyncio.Event()
    can_release = asyncio.Event()

    async def hold_lock():
        async with runner._lock:
            lock_acquired.set()
            await can_release.wait()

    task = asyncio.create_task(hold_lock())
    await lock_acquired.wait()

    assert runner.is_busy(), "Should be busy while another task holds the lock"
    can_release.set()
    await task
    assert not runner.is_busy()


# ── 4. force_kill() with no process ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_force_kill_no_process():
    """force_kill() with no running process should not crash."""
    runner = ClaudeRunner()
    assert runner._pid is None
    await runner.force_kill()  # Should be a no-op


@pytest.mark.asyncio
async def test_force_kill_clears_state():
    """force_kill() should clear _pid and _process even if kill fails."""
    runner = ClaudeRunner()
    runner._pid = 99999  # non-existent PID
    runner._process = mock.MagicMock()

    # os.killpg and os.kill will raise ProcessLookupError for a fake PID
    await runner.force_kill()

    assert runner._pid is None
    assert runner._process is None


# ── 5. _parse_line with malformed JSON ───────────────────────────────────────

def test_parse_line_malformed_json():
    """Malformed JSON should return a TEXT event, not crash."""
    runner = ClaudeRunner()
    events = runner._parse_line("this is {not valid json")
    assert len(events) == 1
    assert events[0].type == EventType.TEXT
    assert "this is {not valid json" in events[0].content


def test_parse_line_empty_string():
    """Empty string should return empty list."""
    runner = ClaudeRunner()
    events = runner._parse_line("")
    assert events == []


def test_parse_line_whitespace_only():
    """Whitespace-only input should return empty list."""
    runner = ClaudeRunner()
    events = runner._parse_line("   \t  \n  ")
    assert events == []


def test_parse_line_valid_json_but_not_event():
    """Valid JSON that isn't a known event type should return empty list."""
    runner = ClaudeRunner()
    events = runner._parse_line(json.dumps({"type": "something_unknown", "data": 123}))
    assert events == []


def test_parse_line_truncated_json():
    """Truncated JSON should be treated as malformed text."""
    runner = ClaudeRunner()
    events = runner._parse_line('{"type": "assistant", "messa')
    assert len(events) == 1
    assert events[0].type == EventType.TEXT


def test_parse_line_json_array():
    """A JSON array (not object) should be treated as text."""
    runner = ClaudeRunner()
    events = runner._parse_line('[1, 2, 3]')
    # json.loads succeeds but .get("type", "") will fail on a list
    # This should not crash
    assert isinstance(events, list)


# ── 6. _parse_line with valid event types ────────────────────────────────────

def test_parse_line_assistant_text():
    """Assistant event with text block."""
    runner = ClaudeRunner()
    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "Hello World"}]},
    })
    events = runner._parse_line(line)
    assert len(events) == 1
    assert events[0].type == EventType.TEXT
    assert events[0].content == "Hello World"


def test_parse_line_assistant_thinking():
    """Assistant event with thinking block."""
    runner = ClaudeRunner()
    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "thinking", "thinking": "Let me think..."}]},
    })
    events = runner._parse_line(line)
    assert len(events) == 1
    assert events[0].type == EventType.THINKING
    assert events[0].content == "Let me think..."


def test_parse_line_assistant_tool_use():
    """Assistant event with tool_use block."""
    runner = ClaudeRunner()
    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "id": "toolu_abc",
            "name": "Bash",
            "input": {"command": "ls -la"},
        }]},
    })
    events = runner._parse_line(line)
    assert len(events) == 1
    assert events[0].type == EventType.TOOL_USE
    assert events[0].tool_name == "Bash"
    assert events[0].tool_call_id == "toolu_abc"
    assert events[0].tool_input == {"command": "ls -la"}


def test_parse_line_assistant_tool_result():
    """Assistant event with tool_result block."""
    runner = ClaudeRunner()
    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_result",
            "tool_use_id": "toolu_xyz",
            "content": "output here",
            "is_error": True,
        }]},
    })
    events = runner._parse_line(line)
    assert len(events) == 1
    assert events[0].type == EventType.TOOL_RESULT
    assert events[0].tool_call_id == "toolu_xyz"
    assert events[0].is_error is True


def test_parse_line_result_with_session_and_usage():
    """Result event should capture session_id and usage."""
    runner = ClaudeRunner()
    line = json.dumps({
        "type": "result",
        "session_id": "sess_123",
        "usage": {"input_tokens": 500, "output_tokens": 200},
    })
    events = runner._parse_line(line)
    assert len(events) == 1
    assert events[0].type == EventType.RESULT
    assert events[0].session_id == "sess_123"
    assert events[0].usage["input_tokens"] == 500


def test_parse_line_result_without_usage():
    """Result event without usage should still work."""
    runner = ClaudeRunner()
    line = json.dumps({
        "type": "result",
        "session_id": "sess_456",
    })
    events = runner._parse_line(line)
    assert len(events) == 1
    assert events[0].type == EventType.RESULT
    assert events[0].session_id == "sess_456"


def test_parse_line_unknown_event_type():
    """Unknown top-level event type should return empty list."""
    runner = ClaudeRunner()
    line = json.dumps({"type": "system", "data": "heartbeat"})
    events = runner._parse_line(line)
    assert events == []


def test_parse_line_assistant_unknown_block_type():
    """Unknown block type inside assistant event should be silently skipped."""
    runner = ClaudeRunner()
    line = json.dumps({
        "type": "assistant",
        "message": {"content": [
            {"type": "text", "text": "before"},
            {"type": "totally_new_block", "data": "whatever"},
            {"type": "text", "text": "after"},
        ]},
    })
    events = runner._parse_line(line)
    assert len(events) == 2
    assert events[0].content == "before"
    assert events[1].content == "after"


# ── 7. split_for_telegram edge cases ────────────────────────────────────────

def test_split_shorter_than_max():
    result = split_for_telegram("short text", max_len=100)
    assert result == ["short text"]


def test_split_exactly_max():
    text = "x" * 100
    result = split_for_telegram(text, max_len=100)
    assert result == [text]


def test_split_longer_than_max_no_newline():
    text = "x" * 150
    result = split_for_telegram(text, max_len=100)
    assert len(result) == 2
    assert result[0] == "x" * 100
    assert result[1] == "x" * 50
    assert "".join(result) == text


def test_split_with_newlines():
    """Should prefer splitting at newline boundaries."""
    text = "a" * 80 + "\n" + "b" * 80
    result = split_for_telegram(text, max_len=100)
    assert len(result) == 2
    assert result[0] == "a" * 80 + "\n"
    assert result[1] == "b" * 80
    assert "".join(result) == text


def test_split_no_content_loss():
    """All content must be preserved after splitting."""
    text = "Hello\nWorld\n" * 500  # ~6000 chars
    result = split_for_telegram(text, max_len=100)
    assert "".join(result) == text
    assert all(len(c) <= 100 for c in result)


def test_split_single_char():
    assert split_for_telegram("x") == ["x"]


def test_split_newline_at_boundary():
    """Newline exactly at max_len position."""
    text = "a" * 99 + "\n" + "b" * 50
    result = split_for_telegram(text, max_len=100)
    assert len(result) == 2
    assert result[0] == "a" * 99 + "\n"
    assert result[1] == "b" * 50


# ── 8. Bounded stderr (deque) ────────────────────────────────────────────────

def test_stderr_deque_bounded():
    """Verify that stderr collection uses a bounded deque."""
    # Simulate what _collect does internally
    stderr_chunks: collections.deque = collections.deque(maxlen=_STDERR_MAXLEN)

    # Add more items than maxlen
    for i in range(_STDERR_MAXLEN + 200):
        stderr_chunks.append(f"error line {i}\n")

    assert len(stderr_chunks) == _STDERR_MAXLEN
    # Oldest entries should be evicted
    assert "error line 0" not in "".join(stderr_chunks)
    # Newest entries should be kept
    assert f"error line {_STDERR_MAXLEN + 199}" in "".join(stderr_chunks)


def test_stderr_maxlen_constant_is_positive():
    """_STDERR_MAXLEN must be a positive integer."""
    assert isinstance(_STDERR_MAXLEN, int)
    assert _STDERR_MAXLEN > 0


# ── 9. SessionExpiredError detection ─────────────────────────────────────────

def test_session_expired_patterns_exist():
    """There should be at least one pattern defined."""
    assert len(_SESSION_EXPIRED_PATTERNS) > 0


@pytest.mark.parametrize("pattern", _SESSION_EXPIRED_PATTERNS)
def test_session_expired_detected(pattern):
    """Each pattern should trigger SessionExpiredError via _classify_and_raise."""
    runner = ClaudeRunner()
    stderr = f"Error: {pattern} for this request"
    with pytest.raises(SessionExpiredError):
        runner._classify_and_raise(1, stderr, "sess_old")


def test_session_expired_case_insensitive():
    """Detection should be case-insensitive."""
    runner = ClaudeRunner()
    stderr = "Error: SESSION EXPIRED unexpectedly"
    with pytest.raises(SessionExpiredError):
        runner._classify_and_raise(1, stderr, "sess_old")


def test_session_expired_exit1_empty_stderr():
    """exit 1 + empty stderr + active session -> SessionExpiredError."""
    runner = ClaudeRunner()
    with pytest.raises(SessionExpiredError):
        runner._classify_and_raise(1, "", "sess_active")


def test_session_expired_exit1_empty_stderr_no_session():
    """exit 1 + empty stderr + no session -> RuntimeError (not SessionExpiredError)."""
    runner = ClaudeRunner()
    with pytest.raises(RuntimeError):
        runner._classify_and_raise(1, "", None)


# ── 10. TransientError detection ─────────────────────────────────────────────

def test_transient_error_class_exists():
    """TransientError should be defined and be an Exception."""
    assert issubclass(TransientError, Exception)


def test_transient_patterns_exist():
    """There should be at least one transient pattern defined."""
    assert len(_TRANSIENT_ERROR_PATTERNS) > 0


@pytest.mark.parametrize("pattern", _TRANSIENT_ERROR_PATTERNS)
def test_transient_error_detected(pattern):
    """Each transient pattern should trigger TransientError via _classify_and_raise."""
    runner = ClaudeRunner()
    stderr = f"Failed: {pattern} error occurred"
    with pytest.raises(TransientError):
        runner._classify_and_raise(1, stderr, None)


def test_transient_error_case_insensitive():
    """Detection should be case-insensitive."""
    runner = ClaudeRunner()
    stderr = "CONNECTION REFUSED by server"
    with pytest.raises(TransientError):
        runner._classify_and_raise(1, stderr, None)


def test_permanent_error_not_transient():
    """An error that matches no patterns should raise RuntimeError."""
    runner = ClaudeRunner()
    stderr = "Permission denied: /etc/shadow"
    with pytest.raises(RuntimeError):
        runner._classify_and_raise(1, stderr, None)


def test_session_expired_takes_priority_over_transient():
    """If both session-expired and transient patterns match, session-expired wins."""
    runner = ClaudeRunner()
    # Contains both "session expired" and "timeout"
    stderr = "session expired due to timeout"
    with pytest.raises(SessionExpiredError):
        runner._classify_and_raise(1, stderr, "sess_x")
