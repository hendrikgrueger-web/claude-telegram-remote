# claude_runner.py
"""ClaudeRunner: Spawnt claude -p als asyncio-Subprocess mit Streaming.
   OutputStreamer: Batched Telegram-Edits mit automatischem Message-Split.
"""

import asyncio
import collections
import json
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


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

CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")
TIMEOUT = int(os.getenv("CLAUDE_TIMEOUT_SECONDS", "300"))
EDIT_INTERVAL = 2.0
MAX_MSG_LEN = 4096
MAX_OUTPUT_SIZE = 10 * 1024 * 1024  # 10 MB stdout cap
_STDERR_MAXLEN = 500  # max stderr lines kept in deque
_LOCK_TIMEOUT_EXTRA = 30  # extra seconds beyond TIMEOUT for lock release
_TERMINATE_TIMEOUT = 5.0
_KILL_TIMEOUT = 3.0
_COLLECT_TIMEOUT_EXTRA = 15  # extra seconds beyond TIMEOUT for _collect

# Globaler Usage-Tracker (letzte Anfrage + kumuliert pro Session)
last_usage: dict = {}
session_usage: dict = {"input_tokens": 0, "output_tokens": 0, "requests": 0}

# Patterns indicating session expiry / invalid session
_SESSION_EXPIRED_PATTERNS = [
    "session not found",
    "invalid session",
    "no such session",
    "session expired",
    "session has expired",
    "conversation not found",
    "resume failed",
    "could not resume",
]

# Patterns indicating transient / retriable errors
_TRANSIENT_ERROR_PATTERNS = [
    "network",
    "connection refused",
    "connection reset",
    "timed out",
    "timeout",
    "rate limit",
    "429",
    "502",
    "503",
    "504",
    "overloaded",
    "temporarily unavailable",
    "econnreset",
    "enotfound",
    "dns",
]


class TransientError(Exception):
    """Retriable error (network, rate-limit, timeout)."""
    pass


def split_for_telegram(text: str, max_len: int = MAX_MSG_LEN) -> list[str]:
    """Teilt Text in Chunks <= max_len, bevorzugt am letzten Newline."""
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


class OutputStreamer:
    def __init__(self, send_fn: Callable, edit_fn: Callable):
        self._send = send_fn
        self._edit = edit_fn
        self._current_msg = None
        self._buffer = ""
        self._last_flush = 0.0

    async def append(self, chunk: str) -> None:
        self._buffer += chunk
        if time.monotonic() - self._last_flush >= EDIT_INTERVAL:
            await self._flush()

    async def finalize(self) -> None:
        await self._flush(force=True)

    async def _flush(self, force: bool = False) -> None:
        if not self._buffer.strip():
            return
        self._last_flush = time.monotonic()
        chunks = split_for_telegram(self._buffer)

        if self._current_msg is None:
            self._current_msg = await self._send(chunks[0])
            for extra in chunks[1:]:
                self._current_msg = await self._send(extra)
        else:
            try:
                await self._edit(self._current_msg, chunks[0])
            except Exception as e:
                logger.debug("Edit fehlgeschlagen: %s", e)
            for extra in chunks[1:]:
                self._current_msg = await self._send(extra)


class SessionExpiredError(Exception):
    pass


def _reap_pid(pid: int) -> None:
    """Reap a zombie process (non-blocking). Silently ignores errors."""
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        pass


def _close_pipe(pipe) -> None:
    """Close a subprocess pipe, ignoring errors."""
    if pipe is None:
        return
    try:
        pipe.close()
    except Exception:
        pass


class ClaudeRunner:
    def __init__(self):
        self._process: Optional[asyncio.subprocess.Process] = None
        self._pid: Optional[int] = None
        self._lock = asyncio.Lock()

    def is_busy(self) -> bool:
        return self._lock.locked()

    async def force_kill(self) -> None:
        """Hard-kill the subprocess using SIGKILL on the process group.
        Always reaps the zombie. Safe to call even when no process is running.
        """
        pid = self._pid
        if pid is None:
            return

        logger.warning("force_kill: sending SIGKILL to pgid/pid %d", pid)

        # Try process group first, fall back to single PID
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass

        _reap_pid(pid)
        self._pid = None
        self._process = None

    async def stop(self) -> None:
        """Gracefully stop the running subprocess. Falls back to SIGKILL."""
        proc = self._process
        pid = self._pid
        if proc is None and pid is None:
            return

        # Phase 1: SIGTERM on process group
        if pid is not None:
            try:
                os.killpg(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                # Fallback to single-process terminate
                if proc is not None:
                    try:
                        proc.terminate()
                    except (ProcessLookupError, OSError):
                        pass

        # Wait for graceful shutdown
        if proc is not None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=_TERMINATE_TIMEOUT)
                _reap_pid(pid) if pid else None
                self._process = None
                self._pid = None
                return
            except (asyncio.TimeoutError, Exception):
                pass

        # Phase 2: SIGKILL on process group
        if pid is not None:
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass

        # Wait briefly for kill to take effect
        if proc is not None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=_KILL_TIMEOUT)
            except (asyncio.TimeoutError, Exception):
                pass

        # Always reap
        if pid is not None:
            _reap_pid(pid)

        self._process = None
        self._pid = None

    async def run(
        self,
        prompt: str,
        directory: str,
        session_id: Optional[str],
        on_event: Callable,
        model: Optional[str] = None,
    ) -> Optional[str]:
        # Wrap the entire locked section with a hard timeout so the lock
        # is guaranteed to be released even if the subprocess hangs.
        lock_timeout = TIMEOUT + _LOCK_TIMEOUT_EXTRA

        async with self._lock:
            try:
                return await asyncio.wait_for(
                    self._run_inner(prompt, directory, session_id, on_event, model),
                    timeout=lock_timeout,
                )
            except asyncio.TimeoutError:
                logger.error("Lock body timed out after %ds, force-killing", lock_timeout)
                await self.force_kill()
                raise

    async def _run_inner(
        self,
        prompt: str,
        directory: str,
        session_id: Optional[str],
        on_event: Callable,
        model: Optional[str] = None,
    ) -> Optional[str]:
        cmd = self._build_cmd(prompt, session_id, model)
        cwd = str(Path(directory).expanduser())
        try:
            env = {**os.environ, "CLAUDE_TELEGRAM_ACTIVE": "1"}
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                start_new_session=True,  # create process group for killpg
            )
            self._pid = self._process.pid
            new_session_id, stderr_output, return_code = await asyncio.wait_for(
                self._collect(on_event),
                timeout=TIMEOUT,
            )
        except asyncio.TimeoutError:
            await self.stop()
            raise
        finally:
            self._process = None
            self._pid = None

        if return_code != 0:
            self._classify_and_raise(return_code, stderr_output, session_id)

        return new_session_id

    def _classify_and_raise(
        self,
        return_code: int,
        stderr_output: str,
        session_id: Optional[str],
    ) -> None:
        """Classify the error and raise the appropriate exception."""
        stderr_lower = stderr_output.lower()

        # Session expired?
        if any(kw in stderr_lower for kw in _SESSION_EXPIRED_PATTERNS):
            raise SessionExpiredError(f"Session abgelaufen: {stderr_output[:200]}")

        # exit 1 with empty stderr + active session -> expired session
        if return_code == 1 and not stderr_output.strip() and session_id:
            raise SessionExpiredError("Session abgelaufen (exit 1, kein stderr)")

        # Transient / retriable error?
        if any(kw in stderr_lower for kw in _TRANSIENT_ERROR_PATTERNS):
            raise TransientError(f"claude exit {return_code} (transient): {stderr_output[:200]}")

        # Permanent error
        raise RuntimeError(f"claude exit {return_code}: {stderr_output[:200]}")

    def _parse_line(self, line: str) -> list[RunEvent]:
        """Parst eine stream-json Zeile in eine Liste von RunEvents."""
        line = line.strip()
        if not line:
            return []
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return [RunEvent(type=EventType.TEXT, content=line + "\n")]

        if not isinstance(event, dict):
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

    async def _collect(self, on_event: Callable):
        assert self._process is not None
        proc = self._process
        new_session_id = None
        stderr_chunks: collections.deque = collections.deque(maxlen=_STDERR_MAXLEN)
        total_stdout_bytes = 0
        output_capped = False

        async def read_stderr():
            async for line in proc.stderr:
                stderr_chunks.append(line.decode("utf-8", errors="replace"))

        async def read_stdout():
            nonlocal new_session_id, total_stdout_bytes, output_capped
            async for line in proc.stdout:
                chunk_size = len(line)
                total_stdout_bytes += chunk_size
                if total_stdout_bytes > MAX_OUTPUT_SIZE:
                    if not output_capped:
                        output_capped = True
                        logger.warning(
                            "stdout exceeded %d bytes (%d total), stopping read",
                            MAX_OUTPUT_SIZE, total_stdout_bytes,
                        )
                    break

                decoded = line.decode("utf-8", errors="replace").strip()
                if not decoded:
                    continue
                for event in self._parse_line(decoded):
                    if event.type == EventType.RESULT and event.session_id:
                        new_session_id = event.session_id
                    await on_event(event)

        # Run readers with a hard timeout to prevent hanging
        collect_timeout = TIMEOUT + _COLLECT_TIMEOUT_EXTRA
        try:
            await asyncio.wait_for(
                asyncio.gather(read_stdout(), read_stderr()),
                timeout=collect_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("_collect timed out after %ds, closing pipes", collect_timeout)
            _close_pipe(proc.stdout)
            _close_pipe(proc.stderr)

        # Wait for process exit (brief, should be fast after pipes close)
        try:
            return_code = await asyncio.wait_for(proc.wait(), timeout=_KILL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("Process did not exit after pipe close, force killing")
            await self.force_kill()
            return_code = -9

        return new_session_id, "".join(stderr_chunks), return_code

    def _build_cmd(self, prompt: str, session_id: Optional[str], model: Optional[str] = None) -> list[str]:
        cmd = [
            CLAUDE_BIN, "-p", prompt,
            "--permission-mode", "auto",
            "--output-format", "stream-json",
            "--verbose",
        ]
        if model:
            cmd += ["--model", model]
        if session_id:
            cmd += ["--resume", session_id]
        return cmd
