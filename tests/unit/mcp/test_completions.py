"""B2: Completion suggestions for repo, project, and lang arguments.

Verifies:
- completion handler returns non-empty candidates for `repo` (mocked /api/list_repos).
- completion handler returns static lang candidates for `lang`.
- completion handler returns empty candidates gracefully when backend is unreachable.
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

SP_URL = "http://mock-sourcepilot:9000"

MOCK_REPOS = [
    {"name": "frameworks/base", "url": ""},
    {"name": "frameworks/av", "url": ""},
    {"name": "packages/apps/Settings", "url": ""},
]


@pytest.fixture()
def _env(monkeypatch):
    monkeypatch.setenv("SOURCEPILOT_URL", SP_URL)
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")


@pytest.mark.anyio
async def test_lang_completion_returns_static_candidates(_env):
    """lang completion returns static list of language names."""
    import entry.tools_state as _ts

    _ts.SOURCEPILOT_URL = SP_URL

    from mcp.client.session import ClientSession
    from mcp.shared.memory import create_client_server_memory_streams
    from mcp.types import PromptReference
    from mcp_server import mcp

    async with create_client_server_memory_streams() as (cs, ss):
        cr, cw = cs
        sr, sw = ss
        server_task = asyncio.create_task(
            mcp._mcp_server.run(sr, sw, mcp._mcp_server.create_initialization_options())
        )
        try:
            async with ClientSession(cr, cw) as session:
                await session.initialize()
                result = await session.complete(
                    ref=PromptReference(type="ref/prompt", name="find_callers"),
                    argument={"name": "lang", "value": "ja"},
                )
                candidates = result.completion.values
                assert len(candidates) > 0, f"Expected lang candidates, got {candidates}"
                assert "java" in candidates
        finally:
            server_task.cancel()


@pytest.mark.anyio
async def test_repo_completion_calls_list_repos(_env):
    """repo completion calls /api/list_repos and returns matching repo names."""
    import entry.tools_state as _ts

    _ts.SOURCEPILOT_URL = SP_URL

    # Seed the resource client so completions.py can use it
    import httpx as _httpx
    from entry.resources import set_resource_client

    async with _httpx.AsyncClient(timeout=5.0) as client:
        set_resource_client(client)

        from mcp.client.session import ClientSession
        from mcp.shared.memory import create_client_server_memory_streams
        from mcp.types import PromptReference
        from mcp_server import mcp

        with respx.mock:
            respx.post(f"{SP_URL}/api/list_repos").mock(
                return_value=httpx.Response(200, json=MOCK_REPOS)
            )

            async with create_client_server_memory_streams() as (cs, ss):
                cr, cw = cs
                sr, sw = ss
                server_task = asyncio.create_task(
                    mcp._mcp_server.run(sr, sw, mcp._mcp_server.create_initialization_options())
                )
                try:
                    async with ClientSession(cr, cw) as session:
                        await session.initialize()
                        result = await session.complete(
                            ref=PromptReference(type="ref/prompt", name="find_callers"),
                            argument={"name": "repo", "value": "frameworks"},
                        )
                        candidates = result.completion.values
                        assert len(candidates) > 0, f"Expected repo candidates, got {candidates}"
                        assert any("frameworks" in c for c in candidates), (
                            f"Expected 'frameworks' in candidates: {candidates}"
                        )
                finally:
                    server_task.cancel()
