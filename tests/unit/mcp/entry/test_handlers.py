"""
MCP handlers 单元测试

测试 entry/handlers.py 中的工具路由、过滤器提取、结果格式化等功能。
"""
import pytest
import respx
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from entry.handlers import (
    _extract_filters,
    _format_results,
    call_tool,
    list_tools,
    _handle_search_code,
    _handle_list_repos,
    _handle_get_file_content,
    SOURCEPILOT_URL,
)
from mcp.types import TextContent


# ─── _extract_filters 测试 ───────────────────────────────

class TestExtractFilters:
    """测试 _extract_filters 从参数中提取过滤字段"""

    def test_full_args(self):
        """所有过滤参数都存在时，全部提取"""
        args = {"lang": "java", "branch": "main", "case_sensitive": "yes"}
        result = _extract_filters(args)
        assert result["lang"] == "java"
        assert result["branch"] == "main"
        assert result["case_sensitive"] == "yes"

    def test_partial_args(self):
        """只有部分参数时，缺失的返回 None"""
        args = {"lang": "python"}
        result = _extract_filters(args)
        assert result["lang"] == "python"
        assert result["branch"] is None
        assert result["case_sensitive"] == "auto"

    def test_empty_args(self):
        """空参数时，lang/branch 为 None，case_sensitive 为 auto"""
        result = _extract_filters({})
        assert result["lang"] is None
        assert result["branch"] is None
        assert result["case_sensitive"] == "auto"

    def test_empty_string_becomes_none(self):
        """空字符串的 lang/branch 应被视为 None"""
        args = {"lang": "", "branch": ""}
        result = _extract_filters(args)
        assert result["lang"] is None
        assert result["branch"] is None


# ─── _format_results 测试 ────────────────────────────────

class TestFormatResults:
    """测试 _format_results 将结果列表格式化为文本"""

    def test_with_results(self):
        """有结果时，格式化为含位置信息的文本"""
        results = [
            {
                "title": "SystemServer.java",
                "content": "private void startBootstrapServices() {",
                "metadata": {
                    "repo": "frameworks/base",
                    "path": "services/core/java/com/android/server/SystemServer.java",
                    "start_line": 120,
                    "end_line": 125,
                },
            }
        ]
        text = _format_results("SystemServer", results)
        assert "1 条" in text
        assert "SystemServer" in text
        assert "frameworks/base" in text
        assert "L120-L125" in text
        assert "startBootstrapServices" in text

    def test_empty_list(self):
        """空结果时，返回包含 '未找到' 的提示"""
        text = _format_results("不存在的查询", [])
        assert "未找到" in text
        assert "不存在的查询" in text

    def test_multiple_results(self):
        """多个结果时，按顺序编号"""
        results = [
            {
                "title": "A.java",
                "content": "class A {}",
                "metadata": {"repo": "repo1", "path": "A.java"},
            },
            {
                "title": "B.java",
                "content": "class B {}",
                "metadata": {"repo": "repo2", "path": "B.java"},
            },
        ]
        text = _format_results("query", results)
        assert "### 1." in text
        assert "### 2." in text

    def test_no_content_preview_skipped(self):
        """content 为 '(no content preview available)' 时不展示代码块"""
        results = [
            {
                "title": "A.java",
                "content": "(no content preview available)",
                "metadata": {"repo": "r", "path": "A.java"},
            }
        ]
        text = _format_results("q", results)
        assert "no content preview" not in text


# ─── list_tools 测试 ────────────────────────────────────

@pytest.mark.asyncio
async def test_list_tools_returns_seven():
    """list_tools 应返回 7 个工具（6 个搜索 + list_projects）"""
    tools = await list_tools()
    assert len(tools) == 7
    names = {t.name for t in tools}
    assert names == {
        "list_projects",
        "search_code",
        "search_symbol",
        "search_file",
        "search_regex",
        "list_repos",
        "get_file_content",
    }


# ─── call_tool 路由测试 ──────────────────────────────────

@pytest.mark.asyncio
async def test_call_tool_unknown():
    """未知工具名返回 'Unknown tool: ...' 消息"""
    result = await call_tool("invalid_tool", {})
    assert len(result) == 1
    assert isinstance(result[0], TextContent)
    assert "Unknown tool: invalid_tool" in result[0].text


@pytest.mark.asyncio
@respx.mock
async def test_call_tool_search_code_routes_correctly():
    """call_tool('search_code', ...) 调用正确的 SourcePilot 端点"""
    respx.post(f"{SOURCEPILOT_URL}/api/search").mock(
        return_value=httpx.Response(200, json=[
            {
                "title": "SystemServer.java",
                "content": "startBootstrapServices",
                "score": 0.9,
                "metadata": {"repo": "frameworks/base", "path": "SystemServer.java"},
            }
        ])
    )

    result = await call_tool("search_code", {"query": "SystemServer"})
    assert len(result) == 1
    assert isinstance(result[0], TextContent)
    assert "SystemServer" in result[0].text


@pytest.mark.asyncio
@respx.mock
async def test_call_tool_exception_returns_error_message():
    """当 _post 抛出异常时，call_tool 返回 '操作出错: ...' 消息"""
    respx.post(f"{SOURCEPILOT_URL}/api/search").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    result = await call_tool("search_code", {"query": "test"})
    assert len(result) == 1
    assert "操作出错" in result[0].text


# ─── _handle_search_code 测试 ────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_handle_search_code_builds_correct_body():
    """_handle_search_code 构造包含 query/repos/top_k/filters 的请求体"""
    import json

    captured_body = {}

    def capture_request(request):
        captured_body.update(json.loads(request.content))
        return httpx.Response(200, json=[])

    respx.post(f"{SOURCEPILOT_URL}/api/search").mock(side_effect=capture_request)

    await _handle_search_code(
        {"query": "startActivity", "repo": "frameworks/base", "top_k": 5, "lang": "java"},
        "trace-123",
    )

    assert captured_body["query"] == "startActivity"
    assert captured_body["repos"] == "frameworks/base"
    assert captured_body["top_k"] == 5
    assert captured_body["lang"] == "java"


@pytest.mark.asyncio
@respx.mock
async def test_handle_search_code_empty_repo_becomes_none():
    """空字符串 repo 参数应被转换为 None（不限制仓库）"""
    import json

    captured_body = {}

    def capture_request(request):
        captured_body.update(json.loads(request.content))
        return httpx.Response(200, json=[])

    respx.post(f"{SOURCEPILOT_URL}/api/search").mock(side_effect=capture_request)

    await _handle_search_code({"query": "test", "repo": ""}, "trace-456")

    assert captured_body["repos"] is None


# ─── _handle_list_repos 测试 ────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_handle_list_repos_empty_returns_not_found():
    """list_repos 返回空列表时，提示 '未找到匹配的仓库'"""
    respx.post(f"{SOURCEPILOT_URL}/api/list_repos").mock(
        return_value=httpx.Response(200, json=[])
    )

    result = await _handle_list_repos({}, "trace-000")
    assert len(result) == 1
    assert "未找到匹配的仓库" in result[0].text


@pytest.mark.asyncio
@respx.mock
async def test_handle_list_repos_with_results():
    """list_repos 返回仓库列表时，格式化输出"""
    respx.post(f"{SOURCEPILOT_URL}/api/list_repos").mock(
        return_value=httpx.Response(200, json=[
            {"name": "frameworks/base", "url": ""},
            {"name": "frameworks/av", "url": "https://example.com/av"},
        ])
    )

    result = await _handle_list_repos({}, "trace-001")
    assert "2 个仓库" in result[0].text
    assert "frameworks/base" in result[0].text
    assert "frameworks/av" in result[0].text


# ─── _handle_get_file_content 测试 ──────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_handle_get_file_content_formats_header():
    """get_file_content 输出包含行号范围的文件头"""
    respx.post(f"{SOURCEPILOT_URL}/api/get_file_content").mock(
        return_value=httpx.Response(200, json={
            "content": "public class SystemServer {}",
            "total_lines": 1000,
            "start_line": 100,
            "end_line": 200,
        })
    )

    result = await _handle_get_file_content(
        {"repo": "frameworks/base", "filepath": "services/SystemServer.java"},
        "trace-002",
    )

    text = result[0].text
    assert "frameworks/base/services/SystemServer.java" in text
    assert "L100-L200" in text
    assert "1000" in text
    assert "```" in text
