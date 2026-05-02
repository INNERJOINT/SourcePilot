"""Tests: B6 — MCP-channel logging with X-Trace-Id.

Verifies:
- get_file_content emits a notifications/message with level "info" containing
  the X-Trace-Id returned by SourcePilot.
- A non-200 upstream response emits a notifications/message with level "warning".
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx
import pytest
import respx

_mcp_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp-server")
if _mcp_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_mcp_dir))


@pytest.fixture()
def _env(monkeypatch):
    monkeypatch.setenv("SOURCEPILOT_URL", "http://mock-sourcepilot:9000")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")


@respx.mock
@pytest.mark.asyncio
async def test_get_file_content_logs_trace_id(_env):
    """get_file_content emits info notification containing the X-Trace-Id header."""
    respx.post("http://mock-sourcepilot:9000/api/get_file_content").mock(
        return_value=httpx.Response(
            200,
            json={
                "total_lines": 10,
                "start_line": 1,
                "end_line": 10,
                "content": "package android.os;",
            },
            headers={"X-Trace-Id": "abc-123"},
        )
    )

    from mcp.client.session import ClientSession
    from mcp.shared.memory import create_client_server_memory_streams
    from mcp_server import mcp

    log_events: list = []

    async def log_cb(params):  # noqa: RUF029
        log_events.append(params)

    async with create_client_server_memory_streams() as (cs, ss):
        cr, cw = cs
        sr, sw = ss
        server_task = asyncio.create_task(
            mcp._mcp_server.run(sr, sw, mcp._mcp_server.create_initialization_options())
        )
        try:
            async with ClientSession(cr, cw, logging_callback=log_cb) as session:
                await session.initialize()
                result = await session.call_tool(
                    "get_file_content",
                    {"inp": {"repo": "frameworks/base", "filepath": "core/Foo.java"}},
                )
                assert not result.isError, f"tool error: {result.content}"
        finally:
            server_task.cancel()

    # At least one info log must contain the trace id from the response header
    info_with_trace = [
        e for e in log_events if e.level == "info" and "abc-123" in str(e.data)
    ]
    assert info_with_trace, (
        f"Expected an info notification with 'abc-123'; got: {log_events}"
    )


@respx.mock
@pytest.mark.asyncio
async def test_non_200_upstream_emits_warning(_env):
    """A non-200 upstream response emits a warning notification."""
    respx.post("http://mock-sourcepilot:9000/api/get_file_content").mock(
        return_value=httpx.Response(503, json={"error": "service unavailable"})
    )

    from mcp.client.session import ClientSession
    from mcp.shared.memory import create_client_server_memory_streams
    from mcp_server import mcp

    log_events: list = []

    async def log_cb(params):  # noqa: RUF029
        log_events.append(params)

    async with create_client_server_memory_streams() as (cs, ss):
        cr, cw = cs
        sr, sw = ss
        server_task = asyncio.create_task(
            mcp._mcp_server.run(sr, sw, mcp._mcp_server.create_initialization_options())
        )
        try:
            async with ClientSession(cr, cw, logging_callback=log_cb) as session:
                await session.initialize()
                result = await session.call_tool(
                    "get_file_content",
                    {"inp": {"repo": "frameworks/base", "filepath": "core/Foo.java"}},
                )
                # tool returns error content when upstream fails
                assert result.isError
        finally:
            server_task.cancel()

    # At least one warning log must mention the non-200 status
    warnings = [e for e in log_events if e.level == "warning"]
    assert warnings, f"Expected a warning notification; got: {log_events}"
    assert any("503" in str(e.data) for e in warnings)
