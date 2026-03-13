"""Tests fuer Permission-Server: Tool-Kategorisierung + async Server-Verhalten."""

import asyncio
import json
import pytest
from permission_server import categorize_tool, ToolCategory, PermissionServer, PermissionRequest


# ---------------------------------------------------------------------------
# Tool-Kategorisierung
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Async Server Tests
# ---------------------------------------------------------------------------

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
