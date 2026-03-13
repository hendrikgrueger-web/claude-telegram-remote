# tests/test_claude_runner.py
"""Tests für split_for_telegram und OutputStreamer."""
import pytest
from claude_runner import split_for_telegram, OutputStreamer


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
