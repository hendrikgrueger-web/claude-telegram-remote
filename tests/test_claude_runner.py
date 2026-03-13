# tests/test_claude_runner.py
"""Tests für split_for_telegram, OutputStreamer und RunEvent/EventType."""
import asyncio
import json
import pytest
from claude_runner import split_for_telegram, OutputStreamer, RunEvent, EventType


# ── split_for_telegram ────────────────────────────────────────────────────────

def test_short_text_not_split():
    assert split_for_telegram("Hallo Welt") == ["Hallo Welt"]


def test_exact_limit_not_split():
    text = "x" * 4096
    assert len(split_for_telegram(text)) == 1


def test_long_text_split_at_newline():
    part1 = "a" * 4000 + "\n"
    part2 = "b" * 200
    result = split_for_telegram(part1 + part2)
    assert len(result) == 2
    assert all(len(c) <= 4096 for c in result)
    assert "".join(result) == part1 + part2


def test_long_text_no_newline_splits_at_limit():
    text = "x" * 5000
    result = split_for_telegram(text)
    assert result == ["x" * 4096, "x" * 904]


def test_very_long_text_no_loss():
    text = "x" * 10000
    result = split_for_telegram(text)
    assert all(len(c) <= 4096 for c in result)
    assert "".join(result) == text


def test_empty_string():
    assert split_for_telegram("") == [""]


# ── OutputStreamer ────────────────────────────────────────────────────────────

@pytest.fixture
def streamer_state():
    sent = []
    edited = {}

    class FakeMsg:
        def __init__(self, idx):
            self.idx = idx

    async def send_fn(text):
        msg = FakeMsg(len(sent))
        sent.append(text)
        return msg

    async def edit_fn(msg, text):
        edited[msg.idx] = text

    return OutputStreamer(send_fn, edit_fn), sent, edited


async def test_streamer_sends_first_message(streamer_state):
    streamer, sent, _ = streamer_state
    await streamer.append("Hallo")
    await streamer.finalize()
    assert len(sent) >= 1
    assert "Hallo" in sent[0]


async def test_streamer_splits_long_content(streamer_state):
    streamer, sent, _ = streamer_state
    big_text = "x" * 5000
    await streamer.append(big_text)
    await streamer.finalize()
    full = "".join(sent)
    assert big_text in full
    assert all(len(s) <= 4096 for s in sent)


async def test_streamer_no_empty_send(streamer_state):
    streamer, sent, _ = streamer_state
    await streamer.append("")
    await streamer.finalize()
    assert len(sent) == 0


# ── RunEvent / _parse_line ────────────────────────────────────────────────────

async def parse_lines(lines: list[str]) -> list[RunEvent]:
    """Parst stream-json Lines ueber ClaudeRunner._parse_line()."""
    from claude_runner import ClaudeRunner
    events = []
    runner = ClaudeRunner()
    for line in lines:
        parsed = runner._parse_line(line)
        if parsed:
            events.extend(parsed)
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
