"""
Gateway 主编排模块单元测试

测试 gateway/gateway.py 中的 search、search_symbol、search_file、
search_regex、list_repos、get_file_content 等函数。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── 辅助工具 ─────────────────────────────────────────────────────────────────

def _make_result(title: str, score: float = 0.8, repo: str = "repo/a",
                 path: str = "path/file.java") -> dict:
    """构造标准搜索结果记录"""
    return {
        "title": title,
        "score": score,
        "content": f"content of {title}",
        "metadata": {"repo": repo, "path": path},
    }


SAMPLE_RESULTS = [
    _make_result("SystemServer.java", score=0.9),
    _make_result("SystemService.java", score=0.7),
]


# ─── search() 函数测试 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSearch:
    """search() 主入口函数测试套件"""

    async def test_exact_path_calls_zoekt_directly(self):
        """query_type='exact' 时直接调用 ZoektAdapter.search_zoekt，不经过 NL 管道"""
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=SAMPLE_RESULTS)
        with patch("gateway.gateway.classify_query", return_value="exact"), \
             patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import search
            result = await search("SystemServer", top_k=5)
            mock_adapter.search_zoekt.assert_called_once()
            assert result == SAMPLE_RESULTS

    async def test_nl_disabled_always_exact_path(self):
        """NL_ENABLED=False 时，即使 classify_query 可能返回 NL，仍走 exact 路径"""
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=SAMPLE_RESULTS)
        with patch("gateway.gateway.config") as mock_config, \
             patch("gateway.gateway.classify_query") as mock_classify, \
             patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            mock_config.NL_ENABLED = False
            from gateway.gateway import search
            result = await search("how does system server start")
            # classify_query 被调用，但 NL_ENABLED=False 时结果被忽略
            mock_adapter.search_zoekt.assert_called_once()
            assert result == SAMPLE_RESULTS

    async def test_nl_path_full_pipeline(self):
        """query_type='natural_language' 时走完整 NL 管道：rewrite → search → rrf → rerank"""
        rewrite_output = [{"query": "SystemServer start"}, {"query": "boot services android"}]
        zoekt_results = [_make_result("SystemServer.java", score=0.5)]

        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=zoekt_results)
        with patch("gateway.gateway.config") as mock_config, \
             patch("gateway.gateway.classify_query", return_value="natural_language"), \
             patch("gateway.gateway.rewrite_query", new=AsyncMock(return_value=rewrite_output)), \
             patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            mock_config.NL_ENABLED = True
            from gateway.gateway import search
            result = await search("how does system server start", top_k=5)
            # 多路并行，search_zoekt 应被调用 2 次（每个重写查询一次）
            assert mock_adapter.search_zoekt.call_count == 2
            assert isinstance(result, list)

    async def test_nl_empty_rewrite_fallback(self):
        """rewrite_query 返回空列表时，降级为直接 Zoekt 搜索"""
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=SAMPLE_RESULTS)
        with patch("gateway.gateway.classify_query", return_value="natural_language"), \
             patch("gateway.gateway.rewrite_query", new=AsyncMock(return_value=[])), \
             patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import search
            result = await search("some query")
            # 降级到直接搜索
            mock_adapter.search_zoekt.assert_called_once()
            assert result == SAMPLE_RESULTS

    async def test_nl_all_routes_fail_fallback(self):
        """所有并行路由都失败时，降级为直接 Zoekt 搜索"""
        rewrite_output = [{"query": "q1"}, {"query": "q2"}]

        call_count = 0

        async def side_effect_search(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # 前两次（并行路由，top_k=20）抛异常，第三次（降级）返回结果
            if kwargs.get("top_k") == 20:
                raise RuntimeError("zoekt unavailable")
            return SAMPLE_RESULTS

        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(side_effect=side_effect_search)
        with patch("gateway.gateway.config") as mock_config, \
             patch("gateway.gateway.classify_query", return_value="natural_language"), \
             patch("gateway.gateway.rewrite_query", new=AsyncMock(return_value=rewrite_output)), \
             patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            mock_config.NL_ENABLED = True
            from gateway.gateway import search
            result = await search("some nl query")
            # 最终降级调用成功
            assert result == SAMPLE_RESULTS

    async def test_score_threshold_filters_results(self):
        """score_threshold 过滤掉分数不足的结果（NL 管道在 rerank 后过滤）"""
        low_score = _make_result("LowScore.java", score=0.1)
        high_score = _make_result("HighScore.java", score=0.9)

        rewrite_output = [{"query": "q1"}]

        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=[low_score, high_score])
        with patch("gateway.gateway.config") as mock_config, \
             patch("gateway.gateway.classify_query", return_value="natural_language"), \
             patch("gateway.gateway.rewrite_query", new=AsyncMock(return_value=rewrite_output)), \
             patch("gateway.gateway.rrf_merge") as mock_rrf, \
             patch("gateway.gateway.feature_rerank") as mock_rerank, \
             patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            mock_config.NL_ENABLED = True
            # rrf_merge 直接返回原始结果，保留原始 score
            mock_rrf.return_value = [high_score, low_score]
            # feature_rerank 也直接返回（保留 score）
            mock_rerank.return_value = [high_score, low_score]
            from gateway.gateway import search
            result = await search("query", score_threshold=0.5)
            # score_threshold=0.5 过滤后只有 high_score 保留
            assert len(result) == 1
            assert result[0]["score"] >= 0.5


# ─── search_symbol() 函数测试 ─────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSearchSymbol:
    """search_symbol() 符号搜索测试套件"""

    async def test_sym_prefix_added(self):
        """搜索时自动添加 sym: 前缀"""
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=SAMPLE_RESULTS)
        with patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import search_symbol
            await search_symbol("SystemServer")
            call_kwargs = mock_adapter.search_zoekt.call_args[1]
            assert call_kwargs["query"] == "sym:SystemServer"

    async def test_sym_fallback_on_empty(self):
        """sym: 搜索无结果时降级为普通搜索"""
        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if "sym:" in kwargs.get("query", ""):
                return []  # sym: 无结果
            return SAMPLE_RESULTS  # 普通搜索有结果

        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(side_effect=side_effect)
        with patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import search_symbol
            result = await search_symbol("SystemServer")
            assert call_count == 2  # 调用了两次：sym: + 普通
            assert result == SAMPLE_RESULTS

    async def test_sym_no_fallback_when_results_exist(self):
        """sym: 搜索有结果时不触发降级"""
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=SAMPLE_RESULTS)
        with patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import search_symbol
            result = await search_symbol("SystemServer")
            assert mock_adapter.search_zoekt.call_count == 1
            assert result == SAMPLE_RESULTS


# ─── search_file() 函数测试 ───────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSearchFile:
    """search_file() 文件搜索测试套件"""

    async def test_file_prefix_added(self):
        """搜索时自动添加 file: 前缀"""
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=SAMPLE_RESULTS)
        with patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import search_file
            await search_file("SystemServer.java")
            call_kwargs = mock_adapter.search_zoekt.call_args[1]
            assert call_kwargs["query"] == "file:SystemServer.java"

    async def test_file_with_extra_query(self):
        """额外查询词追加到 file: 前缀后"""
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=SAMPLE_RESULTS)
        with patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import search_file
            await search_file("SystemServer.java", extra_query="startBootstrap")
            call_kwargs = mock_adapter.search_zoekt.call_args[1]
            assert call_kwargs["query"] == "file:SystemServer.java startBootstrap"


# ─── search_regex() 函数测试 ──────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSearchRegex:
    """search_regex() 正则搜索测试套件"""

    async def test_delegates_to_adapter_search_regex(self):
        """委托给适配器的 search_regex 方法"""
        mock_adapter = MagicMock()
        mock_adapter.search_regex = AsyncMock(return_value=SAMPLE_RESULTS)
        with patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import search_regex
            result = await search_regex(r"start\w+Services")
            mock_adapter.search_regex.assert_called_once()
            call_kwargs = mock_adapter.search_regex.call_args[1]
            assert call_kwargs["pattern"] == r"start\w+Services"
            assert result == SAMPLE_RESULTS


# ─── list_repos() 函数测试 ────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestListRepos:
    """list_repos() 仓库列表测试套件"""

    async def test_delegates_to_adapter_list_repos(self):
        """委托给适配器的 list_repos 方法"""
        repo_list = [{"name": "frameworks/base"}]
        mock_adapter = MagicMock()
        mock_adapter.list_repos = AsyncMock(return_value=repo_list)
        with patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import list_repos
            result = await list_repos(query="frameworks")
            mock_adapter.list_repos.assert_called_once_with(query="frameworks", top_k=50)
            assert result == repo_list


# ─── get_file_content() 函数测试 ──────────────────────────────────────────────

@pytest.mark.asyncio
class TestGetFileContent:
    """get_file_content() 文件内容获取测试套件"""

    async def test_delegates_to_adapter_fetch_file_content(self):
        """委托给适配器的 fetch_file_content 方法"""
        file_content = {
            "content": "L1: package com.android;\n",
            "total_lines": 10,
            "repo": "frameworks/base",
            "filepath": "SystemServer.java",
            "start_line": 1,
            "end_line": 10,
        }
        mock_adapter = MagicMock()
        mock_adapter.fetch_file_content = AsyncMock(return_value=file_content)
        with patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import get_file_content
            result = await get_file_content(
                repo="frameworks/base",
                filepath="SystemServer.java",
                start_line=1,
                end_line=10,
            )
            mock_adapter.fetch_file_content.assert_called_once_with(
                repo="frameworks/base",
                filepath="SystemServer.java",
                start_line=1,
                end_line=10,
            )
            assert result == file_content
