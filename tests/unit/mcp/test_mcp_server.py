"""
MCP Server handler tests (FastMCP)

Uses respx to mock SourcePilot HTTP API responses; no real SourcePilot service required.
Each test creates its own in-memory MCP session to avoid anyio cancel-scope issues.
"""

from contextlib import asynccontextmanager

import httpx
import pytest
import respx
from mcp.shared.memory import create_connected_server_and_client_session
from mcp_server import _lifespan, mcp

SP_URL = "http://mock-sourcepilot:9000"

MOCK_SP_SEARCH_RESULTS = [
    {
        "title": "frameworks/base/services/core/java/com/android/server/SystemServer.java",
        "content": "L120: private void startBootstrapServices() {",
        "score": 0.825,
        "metadata": {
            "repo": "frameworks/base",
            "path": "services/core/java/com/android/server/SystemServer.java",
            "start_line": 117,
            "end_line": 123,
        },
    },
    {
        "title": "frameworks/base/services/core/java/com/android/server/SystemService.java",
        "content": "L45: public abstract class SystemService {",
        "score": 0.634,
        "metadata": {
            "repo": "frameworks/base",
            "path": "services/core/java/com/android/server/SystemService.java",
        },
    },
]

MOCK_SP_LIST_REPOS = [{"name": "frameworks/base", "url": ""}]

MOCK_SP_FILE_CONTENT = {
    "content": "L1: package com.android.server;\nL2: \nL3: import android.os.Process;\n",
    "total_lines": 5,
    "repo": "frameworks/base",
    "filepath": "test.java",
    "start_line": 1,
    "end_line": 5,
}


@asynccontextmanager
async def _mcp_session():
    """Create a fresh in-memory MCP client session with lifespan."""
    async with _lifespan(mcp):
        async with create_connected_server_and_client_session(mcp._mcp_server) as session:
            yield session


# ─── MCP Server tool tests ─────────────────────────────


@pytest.mark.asyncio
async def test_mcp_search_code():
    """MCP search_code tool call → POST /api/search"""
    with respx.mock:
        respx.post(f"{SP_URL}/api/search").mock(
            return_value=httpx.Response(200, json=MOCK_SP_SEARCH_RESULTS)
        )
        async with _mcp_session() as session:
            result = await session.call_tool(
                "search_code",
                {"inp": {"project": "aosp_project", "query": "startBootstrapServices"}},
            )
        text = result.content[0].text
        assert "SystemServer" in text or "startBootstrapServices" in text


@pytest.mark.asyncio
async def test_mcp_search_symbol():
    """MCP search_symbol tool call → POST /api/search_symbol"""
    with respx.mock:
        respx.post(f"{SP_URL}/api/search_symbol").mock(
            return_value=httpx.Response(200, json=MOCK_SP_SEARCH_RESULTS)
        )
        async with _mcp_session() as session:
            result = await session.call_tool(
                "search_symbol", {"inp": {"project": "aosp_project", "symbol": "ActivityManager"}}
            )
        assert "SystemServer" in result.content[0].text


@pytest.mark.asyncio
async def test_mcp_search_file():
    """MCP search_file tool call → POST /api/search_file"""
    with respx.mock:
        respx.post(f"{SP_URL}/api/search_file").mock(
            return_value=httpx.Response(200, json=MOCK_SP_SEARCH_RESULTS)
        )
        async with _mcp_session() as session:
            result = await session.call_tool(
                "search_file", {"inp": {"project": "aosp_project", "path": "SystemServer.java"}}
            )
        assert "SystemServer" in result.content[0].text


@pytest.mark.asyncio
async def test_mcp_search_regex():
    """MCP search_regex tool call → POST /api/search_regex"""
    with respx.mock:
        respx.post(f"{SP_URL}/api/search_regex").mock(
            return_value=httpx.Response(200, json=MOCK_SP_SEARCH_RESULTS)
        )
        async with _mcp_session() as session:
            result = await session.call_tool(
                "search_regex", {"inp": {"project": "aosp_project", "pattern": r"TODO.*fix"}}
            )
        assert "SystemServer" in result.content[0].text


@pytest.mark.asyncio
async def test_mcp_list_repos():
    """MCP list_repos tool call → POST /api/list_repos"""
    with respx.mock:
        respx.post(f"{SP_URL}/api/list_repos").mock(
            return_value=httpx.Response(200, json=MOCK_SP_LIST_REPOS)
        )
        async with _mcp_session() as session:
            result = await session.call_tool("list_repos", {"inp": {"project": "aosp_project"}})
        assert "frameworks/base" in result.content[0].text


@pytest.mark.asyncio
async def test_mcp_get_file_content():
    """MCP get_file_content tool call → POST /api/get_file_content"""
    with respx.mock:
        respx.post(f"{SP_URL}/api/get_file_content").mock(
            return_value=httpx.Response(200, json=MOCK_SP_FILE_CONTENT)
        )
        async with _mcp_session() as session:
            result = await session.call_tool(
                "get_file_content",
                {
                    "inp": {
                        "project": "aosp_project",
                        "repo": "frameworks/base",
                        "filepath": "test.java",
                    }
                },
            )
        assert "package com.android.server" in result.content[0].text


@pytest.mark.asyncio
async def test_mcp_empty_results():
    """When there are no results, returns total=0 / empty hits"""
    with respx.mock:
        respx.post(f"{SP_URL}/api/search").mock(
            return_value=httpx.Response(200, json=[])
        )
        async with _mcp_session() as session:
            result = await session.call_tool(
                "search_code", {"inp": {"project": "aosp_project", "query": "xyz_nonexistent"}}
            )
        text = result.content[0].text
        assert '"total": 0' in text or '"hits": []' in text


# ─── MCP NL search tests ─────────────────────────────


@pytest.mark.asyncio
async def test_mcp_search_nl_query_hits_sourcepilot():
    """Natural language query is correctly forwarded to SourcePilot /api/search"""
    with respx.mock:
        route = respx.post(f"{SP_URL}/api/search").mock(
            return_value=httpx.Response(200, json=MOCK_SP_SEARCH_RESULTS)
        )
        async with _mcp_session() as session:
            result = await session.call_tool(
                "search_code",
                {
                    "inp": {
                        "project": "aosp_project",
                        "query": "How does the Android boot process initialize",
                    }
                },
            )
        assert route.called
        assert result.content


@pytest.mark.asyncio
async def test_mcp_search_exact_query_hits_sourcepilot():
    """Exact query is also forwarded to SourcePilot /api/search"""
    with respx.mock:
        route = respx.post(f"{SP_URL}/api/search").mock(
            return_value=httpx.Response(200, json=MOCK_SP_SEARCH_RESULTS)
        )
        async with _mcp_session() as session:
            result = await session.call_tool(
                "search_code",
                {"inp": {"project": "aosp_project", "query": "startBootstrapServices"}},
            )
        assert route.called
        assert "startBootstrapServices" in result.content[0].text
