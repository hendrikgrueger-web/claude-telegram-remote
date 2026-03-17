# tests/test_bot_stability.py
"""Stability tests for bot.py — edge cases, auth, error handling, None guards."""

import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
import pytest_asyncio

# Set required env vars BEFORE importing bot (module-level globals read at import time)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_USER_ID", "123")
os.environ.setdefault("CLAUDE_BIN", "/bin/echo")

import bot
from bot import (
    ALLOWED_USER_ID,
    HEALTH_FILE,
    _heartbeat_loop,
    _process_prompt,
    authorized_only,
    cmd_status,
    handle_message,
    handle_voice,
    on_permission_request,
    runner,
    ws_manager,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_update(user_id=123, text="hello", has_message=True, has_text=True):
    """Build a minimal mock Update with configurable user_id / message / text."""
    update = MagicMock()
    if not has_message:
        update.message = None
        update.effective_user = MagicMock()
        update.effective_user.id = user_id
        return update

    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = "testuser"
    update.effective_user.full_name = "Test User"

    update.message = AsyncMock()
    update.message.reply_text = AsyncMock()
    if has_text:
        update.message.text = text
    else:
        update.message.text = None
    return update


def _make_context():
    ctx = MagicMock()
    ctx.args = []
    ctx.bot = AsyncMock()
    return ctx


# ── 1. _validate_startup ────────────────────────────────────────────────────


class TestValidateStartup:
    """_validate_startup should sys.exit(1) when required config is missing."""

    def test_missing_token(self):
        with patch.object(bot, "TOKEN", ""), \
             patch.object(bot, "ALLOWED_USER_ID", 123), \
             pytest.raises(SystemExit) as exc_info:
            bot._validate_startup()
        assert exc_info.value.code == 1

    def test_missing_allowed_user_id(self):
        with patch.object(bot, "TOKEN", "tok"), \
             patch.object(bot, "ALLOWED_USER_ID", 0), \
             pytest.raises(SystemExit) as exc_info:
            bot._validate_startup()
        assert exc_info.value.code == 1

    def test_missing_claude_bin(self):
        with patch.object(bot, "TOKEN", "tok"), \
             patch.object(bot, "ALLOWED_USER_ID", 123), \
             patch("bot.CLAUDE_BIN", ""), \
             pytest.raises(SystemExit) as exc_info:
            bot._validate_startup()
        assert exc_info.value.code == 1

    def test_all_present_does_not_exit(self):
        with patch.object(bot, "TOKEN", "tok"), \
             patch.object(bot, "ALLOWED_USER_ID", 123), \
             patch("bot.CLAUDE_BIN", "claude"):
            bot._validate_startup()  # should not raise


# ── 2. authorized_only decorator ────────────────────────────────────────────


class TestAuthorizedOnly:

    @pytest.mark.asyncio
    async def test_correct_user_passes(self):
        @authorized_only
        async def dummy(update, context):
            return "ok"

        update = _make_update(user_id=ALLOWED_USER_ID)
        result = await dummy(update, _make_context())
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_wrong_user_blocked(self):
        called = False

        @authorized_only
        async def dummy(update, context):
            nonlocal called
            called = True
            return "ok"

        update = _make_update(user_id=99999)
        result = await dummy(update, _make_context())
        assert result is None
        assert not called

    @pytest.mark.asyncio
    async def test_none_effective_user(self):
        """When effective_user is None the condition `update.effective_user and ...`
        short-circuits to False, so the handler RUNS (no auth block)."""
        called = False

        @authorized_only
        async def dummy(update, context):
            nonlocal called
            called = True
            return "ok"

        update = _make_update()
        update.effective_user = None
        result = await dummy(update, _make_context())
        # With None user the guard does not block — handler runs
        assert called
        assert result == "ok"


# ── 3. handle_message with None message ─────────────────────────────────────


class TestHandleMessageNone:

    @pytest.mark.asyncio
    async def test_none_message_returns(self):
        update = _make_update(has_message=False)
        # authorized_only sees effective_user.id == 123, passes through
        await handle_message(update, _make_context())
        # No crash = success

    @pytest.mark.asyncio
    async def test_none_text_returns(self):
        update = _make_update(has_text=False)
        await handle_message(update, _make_context())
        update.message.reply_text.assert_not_awaited()


# ── 4. handle_voice with None message ───────────────────────────────────────


class TestHandleVoiceNone:

    @pytest.mark.asyncio
    async def test_none_message_returns(self):
        update = _make_update(has_message=False)
        await handle_voice(update, _make_context())
        # No crash = success


# ── 5. _process_prompt with non-existent workspace directory ────────────────


class TestProcessPromptBadDir:

    @pytest.mark.asyncio
    async def test_nonexistent_dir_sends_error(self, tmp_path):
        fake_dir = str(tmp_path / "does_not_exist")
        update = _make_update()

        with patch.object(ws_manager, "get_active", return_value={
            "directory": fake_dir,
            "session_id": None,
        }), patch.object(ws_manager, "get_active_name", return_value="test"):
            await _process_prompt("hello", update, _make_context())

        update.message.reply_text.assert_awaited()
        args = update.message.reply_text.call_args_list
        # The first reply should mention directory not existing
        assert any("existiert nicht" in str(call) for call in args)


# ── 6. on_permission_request failure → auto-allow ───────────────────────────


class TestOnPermissionRequestFailure:

    @pytest.mark.asyncio
    async def test_send_message_raises_auto_allows(self):
        req = MagicMock()
        req.request_id = "perm_99"
        req.tool_name = "Bash"
        req.tool_input = {"command": "rm -rf /"}
        req.category = MagicMock()
        req.event = asyncio.Event()
        req.decision = None

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(side_effect=RuntimeError("network error"))

        with patch.object(bot, "_bot_instance", mock_bot):
            await on_permission_request(req)

        # Should auto-allow when send fails
        assert req.decision == "allow"
        assert req.event.is_set()


# ── 7. _heartbeat_loop writes HEALTH_FILE ──────────────────────────────────


class TestHeartbeatLoop:

    @pytest.mark.asyncio
    async def test_heartbeat_writes_health_file(self, tmp_path):
        health_file = tmp_path / "bot.health"

        with patch.object(bot, "HEALTH_FILE", health_file):
            # Run one iteration then cancel
            task = asyncio.create_task(_heartbeat_loop())
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert health_file.exists()
        content = health_file.read_text()
        ts = float(content)
        # Should be a recent timestamp (within 5 seconds)
        assert abs(ts - time.time()) < 5


# ── 8. cmd_status when subprocess.run fails ────────────────────────────────


class TestCmdStatus:

    @pytest.mark.asyncio
    async def test_status_subprocess_fails(self):
        update = _make_update()

        with patch("bot.subprocess.run", side_effect=OSError("not found")):
            await cmd_status(update, _make_context())

        update.message.reply_text.assert_awaited_once()
        args_text = update.message.reply_text.call_args[0][0]
        assert "nicht erreichbar" in args_text


# ── 9. handle_message when runner is busy ──────────────────────────────────


class TestHandleMessageBusy:

    @pytest.mark.asyncio
    async def test_busy_response(self):
        update = _make_update(text="do something")

        with patch.object(runner, "is_busy", return_value=True):
            await handle_message(update, _make_context())

        update.message.reply_text.assert_awaited_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "arbeitet noch" in msg or "stop" in msg.lower()
