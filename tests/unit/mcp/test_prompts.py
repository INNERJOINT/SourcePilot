"""Tests: B1 — Prompts primitive (find_callers).

Verifies:
- list_prompts returns the find_callers prompt with correct argument metadata.
- get_prompt(name="find_callers", arguments={"symbol": "foo"}) returns
  serializable messages.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

# Ensure mcp-server is on the path (mirrors conftest.py pattern)
_mcp_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp-server")
if _mcp_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_mcp_dir))


@pytest.fixture()
def _env(monkeypatch):
    monkeypatch.setenv("SOURCEPILOT_URL", "http://mock-sourcepilot:9000")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")


@pytest.mark.asyncio
async def test_list_prompts_returns_find_callers(_env):
    """list_prompts includes find_callers with correct argument metadata."""
    from mcp_server import mcp

    prompts = await mcp.list_prompts()
    names = [p.name for p in prompts]
    assert "find_callers" in names

    fc = next(p for p in prompts if p.name == "find_callers")
    arg_names = [a.name for a in fc.arguments]
    # symbol is required
    assert "symbol" in arg_names
    symbol_arg = next(a for a in fc.arguments if a.name == "symbol")
    assert symbol_arg.required is True
    # repo and project are optional
    assert "repo" in arg_names
    assert "project" in arg_names


@pytest.mark.asyncio
async def test_get_prompt_returns_serializable_messages(_env):
    """get_prompt(find_callers, {symbol: foo}) returns valid serializable messages."""
    from mcp_server import mcp

    result = await mcp.get_prompt("find_callers", {"symbol": "foo"})

    assert result.messages, "messages list must not be empty"
    for msg in result.messages:
        assert msg.role in ("user", "assistant")
        # content must be serializable
        json.dumps(msg.content.model_dump())

    # symbol should appear in the guidance text
    combined = " ".join(m.content.text for m in result.messages)
    assert "foo" in combined


@pytest.mark.asyncio
async def test_get_prompt_with_repo_and_project(_env):
    """find_callers includes repo and project hints when provided."""
    from mcp_server import mcp

    result = await mcp.get_prompt(
        "find_callers",
        {"symbol": "startActivity", "repo": "frameworks/base", "project": "aosp-14"},
    )

    combined = " ".join(m.content.text for m in result.messages)
    assert "startActivity" in combined
    assert "frameworks/base" in combined
    assert "aosp-14" in combined


@pytest.mark.asyncio
async def test_list_prompts_via_in_memory_session(_env):
    """list_prompts round-trip over in-memory MCP session returns find_callers."""
    from mcp.client.session import ClientSession
    from mcp.shared.memory import create_client_server_memory_streams
    from mcp_server import mcp

    async with create_client_server_memory_streams() as (cs, ss):
        cr, cw = cs
        sr, sw = ss
        server_task = asyncio.create_task(
            mcp._mcp_server.run(
                sr, sw, mcp._mcp_server.create_initialization_options()
            )
        )
        try:
            async with ClientSession(cr, cw) as session:
                await session.initialize()
                result = await session.list_prompts()
                names = [p.name for p in result.prompts]
                assert "find_callers" in names
        finally:
            server_task.cancel()


@pytest.mark.asyncio
async def test_get_prompt_via_in_memory_session(_env):
    """get_prompt(find_callers) round-trip over in-memory session returns messages."""
    from mcp.client.session import ClientSession
    from mcp.shared.memory import create_client_server_memory_streams
    from mcp_server import mcp

    async with create_client_server_memory_streams() as (cs, ss):
        cr, cw = cs
        sr, sw = ss
        server_task = asyncio.create_task(
            mcp._mcp_server.run(
                sr, sw, mcp._mcp_server.create_initialization_options()
            )
        )
        try:
            async with ClientSession(cr, cw) as session:
                await session.initialize()
                result = await session.get_prompt("find_callers", {"symbol": "foo"})
                assert result.messages
                combined = " ".join(m.content.text for m in result.messages)
                assert "foo" in combined
        finally:
            server_task.cancel()
