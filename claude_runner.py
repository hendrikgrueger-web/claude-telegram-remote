# claude_runner.py
"""ClaudeRunner: Spawnt claude -p als asyncio-Subprocess mit Streaming.
   OutputStreamer: Batched Telegram-Edits mit automatischem Message-Split.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")
TIMEOUT = int(os.getenv("CLAUDE_TIMEOUT_SECONDS", "300"))
EDIT_INTERVAL = 2.0
MAX_MSG_LEN = 4096

# Globaler Usage-Tracker (letzte Anfrage + kumuliert pro Session)
last_usage: dict = {}
session_usage: dict = {"input_tokens": 0, "output_tokens": 0, "requests": 0}


def split_for_telegram(text: str, max_len: int = MAX_MSG_LEN) -> list[str]:
    """Teilt Text in Chunks ≤ max_len, bevorzugt am letzten Newline."""
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


class ClaudeRunner:
    def __init__(self):
        self._process: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()

    def is_busy(self) -> bool:
        return self._lock.locked()

    async def stop(self) -> None:
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            finally:
                self._process = None

    async def run(
        self,
        prompt: str,
        directory: str,
        session_id: Optional[str],
        on_chunk: Callable,
        model: Optional[str] = None,
    ) -> Optional[str]:
        async with self._lock:
            cmd = self._build_cmd(prompt, session_id, model)
            cwd = str(Path(directory).expanduser())
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                )
                new_session_id, stderr_output, return_code = await asyncio.wait_for(
                    self._collect(on_chunk),
                    timeout=TIMEOUT,
                )
            except asyncio.TimeoutError:
                await self.stop()
                raise
            finally:
                self._process = None

            if return_code != 0:
                stderr_lower = stderr_output.lower()
                if any(kw in stderr_lower for kw in ["session not found", "invalid session", "no such session"]):
                    raise SessionExpiredError(f"Session abgelaufen: {stderr_output[:200]}")
                raise RuntimeError(f"claude exit {return_code}: {stderr_output[:200]}")

            return new_session_id

    async def _collect(self, on_chunk: Callable):
        assert self._process is not None
        new_session_id = None
        stderr_chunks = []

        async def read_stderr():
            async for line in self._process.stderr:
                stderr_chunks.append(line.decode("utf-8", errors="replace"))

        async def read_stdout():
            nonlocal new_session_id
            async for line in self._process.stdout:
                line = line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    await on_chunk(line + "\n")
                    continue
                event_type = event.get("type", "")
                if event_type == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        if block.get("type") == "text":
                            await on_chunk(block["text"])
                elif event_type == "result":
                    new_session_id = event.get("session_id")
                    usage = event.get("usage", {})
                    if usage:
                        last_usage.clear()
                        last_usage.update(usage)
                        session_usage["input_tokens"] += usage.get("input_tokens", 0)
                        session_usage["output_tokens"] += usage.get("output_tokens", 0)
                        session_usage["requests"] += 1

        await asyncio.gather(read_stdout(), read_stderr())
        return_code = await self._process.wait()
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
