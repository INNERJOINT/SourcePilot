"""
MCP Server 处理器测试

使用 respx 模拟 SourcePilot HTTP API 响应，无需运行真实的 SourcePilot 服务。
MCP 层通过 httpx 调用 SourcePilot，不再直接访问 Zoekt。
"""

import json
import pytest
import respx
import httpx

from mcp_server import call_tool

# ─── SourcePilot API Mock 数据 ────────────────────────

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

MOCK_SP_LIST_REPOS = [
    {"name": "frameworks/base", "url": ""},
]

MOCK_SP_FILE_CONTENT = {
    "content": "L1: package com.android.server;\nL2: \nL3: import android.os.Process;\nL4: \nL5: public class SystemServer {",
    "total_lines": 5,
    "repo": "frameworks/base",
    "filepath": "test.java",
    "start_line": 1,
    "end_line": 5,
}

SP_URL = "http://mock-sourcepilot:9000"


# ─── MCP Server 工具测试 ─────────────────────────────

class TestMCPTools:
    """测试 MCP Server 工具路由和格式化（通过 SourcePilot HTTP API）"""

    @pytest.mark.asyncio
    async def test_mcp_search_code(self):
        """MCP search_code 工具调用 → POST /api/search"""
        with respx.mock:
            respx.post(f"{SP_URL}/api/search").mock(
                return_value=httpx.Response(200, json=MOCK_SP_SEARCH_RESULTS)
            )

            result = await call_tool("search_code", {"query": "startBootstrapServices"})

            assert len(result) == 1
            assert result[0].type == "text"
            assert "startBootstrapServices" in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_search_symbol(self):
        """MCP search_symbol 工具调用 → POST /api/search_symbol"""
        with respx.mock:
            respx.post(f"{SP_URL}/api/search_symbol").mock(
                return_value=httpx.Response(200, json=MOCK_SP_SEARCH_RESULTS)
            )

            result = await call_tool("search_symbol", {"symbol": "ActivityManager"})

            assert len(result) == 1
            assert result[0].type == "text"
            assert "SystemServer" in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_search_file(self):
        """MCP search_file 工具调用 → POST /api/search_file"""
        with respx.mock:
            respx.post(f"{SP_URL}/api/search_file").mock(
                return_value=httpx.Response(200, json=MOCK_SP_SEARCH_RESULTS)
            )

            result = await call_tool("search_file", {"path": "SystemServer.java"})

            assert len(result) == 1
            assert result[0].type == "text"
            assert "SystemServer" in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_search_regex(self):
        """MCP search_regex 工具调用 → POST /api/search_regex"""
        with respx.mock:
            respx.post(f"{SP_URL}/api/search_regex").mock(
                return_value=httpx.Response(200, json=MOCK_SP_SEARCH_RESULTS)
            )

            result = await call_tool("search_regex", {"pattern": r"TODO.*fix"})

            assert len(result) == 1
            assert result[0].type == "text"
            assert "SystemServer" in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_list_repos(self):
        """MCP list_repos 工具调用 → POST /api/list_repos"""
        with respx.mock:
            respx.post(f"{SP_URL}/api/list_repos").mock(
                return_value=httpx.Response(200, json=MOCK_SP_LIST_REPOS)
            )

            result = await call_tool("list_repos", {"query": "frameworks"})

            assert len(result) == 1
            assert result[0].type == "text"
            assert "frameworks/base" in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_get_file_content(self):
        """MCP get_file_content 工具调用 → POST /api/get_file_content"""
        with respx.mock:
            respx.post(f"{SP_URL}/api/get_file_content").mock(
                return_value=httpx.Response(200, json=MOCK_SP_FILE_CONTENT)
            )

            result = await call_tool("get_file_content", {
                "repo": "frameworks/base",
                "filepath": "test.java",
            })

            assert len(result) == 1
            assert "package com.android.server" in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_unknown_tool(self):
        """未知工具返回错误消息"""
        result = await call_tool("nonexistent_tool", {})
        assert "Unknown tool" in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_empty_results(self):
        """无结果时返回友好提示"""
        with respx.mock:
            respx.post(f"{SP_URL}/api/search").mock(
                return_value=httpx.Response(200, json=[])
            )

            result = await call_tool("search_code", {"query": "xyz_nonexistent"})
            assert "未找到" in result[0].text


# ─── MCP NL 搜索测试 ─────────────────────────────────

class TestMCPNLSearch:
    """测试 MCP Server search_code 对不同查询类型的处理。

    MCP 层不再区分 NL/exact 查询 — 所有查询都转发给 SourcePilot。
    这些测试验证无论查询内容是什么，都正确调用 SourcePilot /api/search 并返回结果。
    """

    @pytest.mark.asyncio
    async def test_mcp_search_nl_query_hits_sourcepilot(self):
        """自然语言查询正确转发到 SourcePilot /api/search"""
        with respx.mock:
            route = respx.post(f"{SP_URL}/api/search").mock(
                return_value=httpx.Response(200, json=MOCK_SP_SEARCH_RESULTS)
            )

            result = await call_tool("search_code", {"query": "Android 启动流程怎么初始化"})

            assert route.called
            assert result[0].type == "text"
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_mcp_search_exact_query_hits_sourcepilot(self):
        """精确查询同样转发到 SourcePilot /api/search"""
        with respx.mock:
            route = respx.post(f"{SP_URL}/api/search").mock(
                return_value=httpx.Response(200, json=MOCK_SP_SEARCH_RESULTS)
            )

            result = await call_tool("search_code", {"query": "startBootstrapServices"})

            assert route.called
            assert "startBootstrapServices" in result[0].text
