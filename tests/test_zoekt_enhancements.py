"""
Zoekt Client & MCP Server 自动化测试

使用 respx 模拟 Zoekt HTTP 响应，无需运行真实的 Zoekt 服务。
测试覆盖所有 zoekt_client 函数和 MCP 工具。
"""

import json
import math
import sys
import os
import pytest
import respx
import httpx

# 确保能 import 项目模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "aosp_search"))

# 设定环境变量（在 import config 之前）
os.environ["ZOEKT_URL"] = "http://mock-zoekt:6070"
os.environ["API_KEY"] = "test-key"
os.environ["NL_ENABLED"] = "false"

from aosp_search import zoekt_client
from aosp_search import config


# ─── Mock 数据 ────────────────────────────────────────

MOCK_SEARCH_RESPONSE = {
    "Result": {
        "FileMatches": [
            {
                "Repo": "frameworks/base",
                "FileName": "services/core/java/com/android/server/SystemServer.java",
                "Score": 25.5,
                "Matches": [
                    {
                        "LineNum": 120,
                        "Fragments": [
                            {"Pre": "private void ", "Match": "startBootstrapServices", "Post": "() {"}
                        ]
                    }
                ]
            },
            {
                "Repo": "frameworks/base",
                "FileName": "services/core/java/com/android/server/SystemService.java",
                "Score": 15.2,
                "Matches": [
                    {
                        "LineNum": 45,
                        "Fragments": [
                            {"Pre": "public abstract class ", "Match": "SystemService", "Post": " {"}
                        ]
                    }
                ]
            },
        ],
        "Stats": {"MatchCount": 2, "FileCount": 2}
    }
}

MOCK_EMPTY_RESPONSE = {
    "Result": {
        "FileMatches": [],
        "Stats": {"MatchCount": 0, "FileCount": 0}
    }
}

MOCK_PRINT_RESPONSE_HTML = """
<html><body>
<pre><span class="noselect"><a href="#l1">1</a>: </span>package com.android.server;</pre>
<pre><span class="noselect"><a href="#l2">2</a>: </span></pre>
<pre><span class="noselect"><a href="#l3">3</a>: </span>import android.os.Process;</pre>
<pre><span class="noselect"><a href="#l4">4</a>: </span></pre>
<pre><span class="noselect"><a href="#l5">5</a>: </span>public class SystemServer {</pre>
</body></html>
"""


# ─── zoekt_client.search() 测试 ──────────────────────

class TestSearch:
    """测试 zoekt_client.search() 函数"""

    @pytest.mark.asyncio
    async def test_basic_search(self):
        """基本搜索能返回正确结构的 records"""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            results = await zoekt_client.search(query="startBootstrapServices", top_k=5)

            assert len(results) == 2
            assert results[0]["title"] == "frameworks/base/services/core/java/com/android/server/SystemServer.java"
            assert results[0]["metadata"]["repo"] == "frameworks/base"
            assert results[0]["metadata"]["path"] == "services/core/java/com/android/server/SystemServer.java"
            assert "content" in results[0]
            assert "score" in results[0]

    @pytest.mark.asyncio
    async def test_search_with_repo_filter(self):
        """repo 过滤参数正确拼入查询"""
        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await zoekt_client.search(query="test", repos="frameworks/base")

            # 验证查询包含 r: 前缀
            request = route.calls[0].request
            q_param = str(request.url.params.get("q", ""))
            assert "r:frameworks/base" in q_param

    @pytest.mark.asyncio
    async def test_search_with_lang_filter(self):
        """lang 过滤参数正确拼入查询"""
        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await zoekt_client.search(query="test", lang="java")

            request = route.calls[0].request
            q_param = str(request.url.params.get("q", ""))
            assert "lang:java" in q_param

    @pytest.mark.asyncio
    async def test_search_with_branch_filter(self):
        """branch 过滤参数正确拼入查询"""
        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await zoekt_client.search(query="test", branch="main")

            request = route.calls[0].request
            q_param = str(request.url.params.get("q", ""))
            assert "branch:main" in q_param

    @pytest.mark.asyncio
    async def test_search_with_case_sensitive(self):
        """case_sensitive 参数正确拼入查询"""
        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await zoekt_client.search(query="Test", case_sensitive="yes")

            request = route.calls[0].request
            q_param = str(request.url.params.get("q", ""))
            assert "case:yes" in q_param

    @pytest.mark.asyncio
    async def test_search_case_auto_not_added(self):
        """case_sensitive='auto' 时不应添加 case: 前缀"""
        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await zoekt_client.search(query="test", case_sensitive="auto")

            request = route.calls[0].request
            q_param = str(request.url.params.get("q", ""))
            assert "case:" not in q_param

    @pytest.mark.asyncio
    async def test_search_combined_filters(self):
        """多个过滤器可组合使用"""
        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await zoekt_client.search(
                query="startActivity",
                repos="frameworks/base",
                lang="java",
                branch="main",
                case_sensitive="yes",
            )

            request = route.calls[0].request
            q_param = str(request.url.params.get("q", ""))
            assert "r:frameworks/base" in q_param
            assert "lang:java" in q_param
            assert "branch:main" in q_param
            assert "case:yes" in q_param
            assert "startActivity" in q_param

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        """Zoekt 返回空结果"""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_EMPTY_RESPONSE)
            )

            results = await zoekt_client.search(query="nonexistent_symbol")
            assert results == []

    @pytest.mark.asyncio
    async def test_search_418_teapot(self):
        """Zoekt 返回 418 表示无结果"""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(418, text="I'm a teapot")
            )

            results = await zoekt_client.search(query="nothing")
            assert results == []

    @pytest.mark.asyncio
    async def test_search_score_normalization_with_zoekt_score(self):
        """有 Score 字段时使用 sigmoid 归一化"""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            results = await zoekt_client.search(query="test")

            # Score 25.5 → sigmoid(0.1 * (25.5 - 10)) = sigmoid(1.55) ≈ 0.825
            expected = round(1.0 / (1.0 + math.exp(-0.1 * (25.5 - 10))), 4)
            assert results[0]["score"] == expected

    @pytest.mark.asyncio
    async def test_search_score_threshold(self):
        """score_threshold 能过滤低分结果"""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            results = await zoekt_client.search(query="test", score_threshold=0.99)
            # 两条结果的归一化分数都应低于 0.99
            assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_top_k(self):
        """top_k 限制返回数量"""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            results = await zoekt_client.search(query="test", top_k=1)
            assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_context_lines_param(self):
        """NUM_CONTEXT_LINES > 0 时应传入 ctx 参数"""
        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await zoekt_client.search(query="test")

            request = route.calls[0].request
            ctx_param = request.url.params.get("ctx", "")
            if config.NUM_CONTEXT_LINES > 0:
                assert ctx_param == str(config.NUM_CONTEXT_LINES)


# ─── zoekt_client.search_regex() 测试 ────────────────

class TestSearchRegex:
    """测试 zoekt_client.search_regex() 函数"""

    @pytest.mark.asyncio
    async def test_regex_query_format(self):
        """正则搜索使用 content:/pattern/ 格式"""
        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await zoekt_client.search_regex(pattern=r"func\s+\w+")

            request = route.calls[0].request
            q_param = str(request.url.params.get("q", ""))
            assert "content:/" in q_param

    @pytest.mark.asyncio
    async def test_regex_with_lang(self):
        """正则搜索支持 lang 过滤"""
        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await zoekt_client.search_regex(pattern="TODO.*fix", lang="java")

            request = route.calls[0].request
            q_param = str(request.url.params.get("q", ""))
            assert "lang:java" in q_param

    @pytest.mark.asyncio
    async def test_regex_with_repo(self):
        """正则搜索支持 repo 过滤"""
        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await zoekt_client.search_regex(
                pattern="TODO", repos="frameworks/base"
            )

            request = route.calls[0].request
            q_param = str(request.url.params.get("q", ""))
            assert "r:frameworks/base" in q_param


# ─── zoekt_client.list_repos() 测试 ──────────────────

class TestListRepos:
    """测试 zoekt_client.list_repos() 函数"""

    @pytest.mark.asyncio
    async def test_list_repos_query(self):
        """list_repos 使用 type:repo 查询"""
        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await zoekt_client.list_repos(query="frameworks")

            request = route.calls[0].request
            q_param = str(request.url.params.get("q", ""))
            assert "type:repo" in q_param
            assert "r:frameworks" in q_param

    @pytest.mark.asyncio
    async def test_list_repos_no_query(self):
        """无 query 时只用 type:repo"""
        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await zoekt_client.list_repos()

            request = route.calls[0].request
            q_param = str(request.url.params.get("q", ""))
            assert q_param == "type:repo"

    @pytest.mark.asyncio
    async def test_list_repos_dedup(self):
        """list_repos 从 FileMatches 提取去重的 repo"""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            repos = await zoekt_client.list_repos()

            # MOCK 数据两条都是 frameworks/base，去重后应只有 1 个
            assert len(repos) == 1
            assert repos[0]["name"] == "frameworks/base"

    @pytest.mark.asyncio
    async def test_list_repos_empty(self):
        """无匹配仓库时返回空列表"""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(418, text="I'm a teapot")
            )

            repos = await zoekt_client.list_repos()
            assert repos == []


# ─── zoekt_client.fetch_file_content() 测试 ──────────

class TestFetchFileContent:
    """测试 zoekt_client.fetch_file_content() 函数"""

    @pytest.mark.asyncio
    async def test_fetch_full_file(self):
        """获取完整文件内容"""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/print").mock(
                return_value=httpx.Response(200, text=MOCK_PRINT_RESPONSE_HTML)
            )

            result = await zoekt_client.fetch_file_content(
                repo="frameworks/base",
                filepath="services/core/java/com/android/server/SystemServer.java",
            )

            assert result["total_lines"] == 5
            assert result["start_line"] == 1
            assert result["end_line"] == 5
            assert result["repo"] == "frameworks/base"
            assert "package com.android.server;" in result["content"]

    @pytest.mark.asyncio
    async def test_fetch_line_range(self):
        """指定行范围"""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/print").mock(
                return_value=httpx.Response(200, text=MOCK_PRINT_RESPONSE_HTML)
            )

            result = await zoekt_client.fetch_file_content(
                repo="frameworks/base",
                filepath="test.java",
                start_line=2,
                end_line=4,
            )

            assert result["start_line"] == 2
            assert result["end_line"] == 4
            # 应只有 3 行
            lines = result["content"].split("\n")
            assert len(lines) == 3

    @pytest.mark.asyncio
    async def test_fetch_file_not_found(self):
        """文件不存在时抛出 FileNotFoundError"""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/print").mock(
                return_value=httpx.Response(418, text="I'm a teapot")
            )

            with pytest.raises(FileNotFoundError):
                await zoekt_client.fetch_file_content(
                    repo="nonexistent",
                    filepath="not/a/file.java",
                )

    @pytest.mark.asyncio
    async def test_fetch_line_numbers_in_output(self):
        """输出中包含行号前缀"""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/print").mock(
                return_value=httpx.Response(200, text=MOCK_PRINT_RESPONSE_HTML)
            )

            result = await zoekt_client.fetch_file_content(
                repo="test", filepath="test.java"
            )

            assert "L1:" in result["content"]
            assert "L5:" in result["content"]


# ─── _build_content_snippet() 测试 ───────────────────

class TestBuildContentSnippet:
    """测试代码片段构建"""

    def test_normal_fragments(self):
        """正常的 Fragments 拼接"""
        fm = {
            "Matches": [
                {
                    "LineNum": 42,
                    "Fragments": [
                        {"Pre": "private void ", "Match": "startBootstrap", "Post": "() {"}
                    ]
                }
            ]
        }
        result = zoekt_client._build_content_snippet(fm)
        assert "L42:" in result
        assert "startBootstrap" in result

    def test_no_matches(self):
        """无匹配时返回占位文本"""
        result = zoekt_client._build_content_snippet({"Matches": []})
        assert result == "(no content preview available)"

    def test_multiple_matches(self):
        """多行匹配"""
        fm = {
            "Matches": [
                {
                    "LineNum": 10,
                    "Fragments": [{"Pre": "", "Match": "line10", "Post": ""}]
                },
                {
                    "LineNum": 20,
                    "Fragments": [{"Pre": "", "Match": "line20", "Post": ""}]
                },
            ]
        }
        result = zoekt_client._build_content_snippet(fm)
        assert "L10:" in result
        assert "L20:" in result
        assert "line10" in result
        assert "line20" in result


# ─── MCP Server 工具测试 ─────────────────────────────

class TestMCPTools:
    """测试 MCP Server 工具路由和格式化"""

    @pytest.mark.asyncio
    async def test_mcp_search_code(self):
        """MCP search_code 工具调用"""
        from aosp_search.mcp_server import call_tool

        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            result = await call_tool("search_code", {"query": "startBootstrapServices"})

            assert len(result) == 1
            assert result[0].type == "text"
            assert "startBootstrapServices" in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_search_code_with_filters(self):
        """MCP search_code 工具支持过滤参数"""
        from aosp_search.mcp_server import call_tool

        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await call_tool("search_code", {
                "query": "startActivity",
                "lang": "java",
                "branch": "main",
                "case_sensitive": "yes",
            })

            request = route.calls[0].request
            q_param = str(request.url.params.get("q", ""))
            assert "lang:java" in q_param
            assert "branch:main" in q_param
            assert "case:yes" in q_param

    @pytest.mark.asyncio
    async def test_mcp_search_symbol(self):
        """MCP search_symbol 工具使用 sym: 前缀"""
        from aosp_search.mcp_server import call_tool

        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await call_tool("search_symbol", {"symbol": "ActivityManager"})

            request = route.calls[0].request
            q_param = str(request.url.params.get("q", ""))
            assert "sym:ActivityManager" in q_param

    @pytest.mark.asyncio
    async def test_mcp_search_file(self):
        """MCP search_file 工具使用 file: 前缀"""
        from aosp_search.mcp_server import call_tool

        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await call_tool("search_file", {"path": "SystemServer.java"})

            request = route.calls[0].request
            q_param = str(request.url.params.get("q", ""))
            assert "file:SystemServer.java" in q_param

    @pytest.mark.asyncio
    async def test_mcp_search_regex(self):
        """MCP search_regex 工具"""
        from aosp_search.mcp_server import call_tool

        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            result = await call_tool("search_regex", {"pattern": r"TODO.*fix"})

            assert len(result) == 1
            assert result[0].type == "text"
            request = route.calls[0].request
            q_param = str(request.url.params.get("q", ""))
            assert "content:/" in q_param

    @pytest.mark.asyncio
    async def test_mcp_list_repos(self):
        """MCP list_repos 工具"""
        from aosp_search.mcp_server import call_tool

        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            result = await call_tool("list_repos", {"query": "frameworks"})

            assert len(result) == 1
            assert result[0].type == "text"
            assert "frameworks/base" in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_get_file_content(self):
        """MCP get_file_content 工具"""
        from aosp_search.mcp_server import call_tool

        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/print").mock(
                return_value=httpx.Response(200, text=MOCK_PRINT_RESPONSE_HTML)
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
        from aosp_search.mcp_server import call_tool

        result = await call_tool("nonexistent_tool", {})
        assert "Unknown tool" in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_empty_results(self):
        """无结果时返回友好提示"""
        from aosp_search.mcp_server import call_tool

        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_EMPTY_RESPONSE)
            )

            result = await call_tool("search_code", {"query": "xyz_nonexistent"})
            assert "未找到" in result[0].text


# ─── MCP NL 增强搜索测试 ───────────────────────────────

class TestMCPNLSearch:
    """测试 MCP Server search_code 的 NL 增强路径"""

    @pytest.mark.asyncio
    async def test_mcp_search_code_nl_enabled(self):
        """NL_ENABLED=true + 自然语言查询 → 走 NL 管道"""
        from unittest.mock import patch, AsyncMock
        from aosp_search.mcp_server import call_tool

        original_nl = config.NL_ENABLED
        config.NL_ENABLED = True
        try:
            mock_nl = AsyncMock(return_value=[
                {"title": "frameworks/base/Test.java", "content": "test code",
                 "score": 0.9, "metadata": {"repo": "frameworks/base", "path": "Test.java"}},
            ])
            with patch("aosp_search.nl_search.nl_search", mock_nl) as patched:
                # 使用 import 后直接 patch mcp_server 中的延迟导入
                with patch.dict("sys.modules", {}):
                    pass
                # 直接 patch nl_search 模块级函数
                import aosp_search.nl_search
                with patch.object(aosp_search.nl_search, "nl_search", mock_nl):
                    result = await call_tool("search_code", {"query": "Android 启动流程怎么初始化"})

                    assert mock_nl.called
                    assert result[0].type == "text"
        finally:
            config.NL_ENABLED = original_nl

    @pytest.mark.asyncio
    async def test_mcp_search_code_nl_exact_passthrough(self):
        """NL_ENABLED=true + 精确查询 → 直接走 zoekt_client"""
        from aosp_search.mcp_server import call_tool

        original_nl = config.NL_ENABLED
        config.NL_ENABLED = True
        try:
            with respx.mock:
                route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                    return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
                )

                result = await call_tool("search_code", {"query": "startBootstrapServices"})

                assert route.called
                assert "startBootstrapServices" in result[0].text
        finally:
            config.NL_ENABLED = original_nl

    @pytest.mark.asyncio
    async def test_mcp_search_code_nl_disabled(self):
        """NL_ENABLED=false → 直接走 zoekt_client，不触发 NL"""
        from aosp_search.mcp_server import call_tool

        original_nl = config.NL_ENABLED
        config.NL_ENABLED = False
        try:
            with respx.mock:
                route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                    return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
                )

                result = await call_tool("search_code", {"query": "Android 启动流程怎么初始化"})

                assert route.called
                assert result[0].type == "text"
        finally:
            config.NL_ENABLED = original_nl
