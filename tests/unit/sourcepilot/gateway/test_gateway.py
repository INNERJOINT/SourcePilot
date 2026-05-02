"""
Unit tests for the gateway orchestration module

Tests search, search_symbol, search_file, search_regex, list_repos,
and get_file_content in gateway/gateway.py.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Helper utilities ─────────────────────────────────────────────────────────

def _make_result(title: str, score: float = 0.8, repo: str = "repo/a",
                 path: str = "path/file.java") -> dict:
    """Build a standard search result record."""
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


# ─── search() function tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSearch:
    """Test suite for the search() main entry-point function."""

    async def test_exact_path_calls_zoekt_directly(self):
        """When query_type='exact', ZoektAdapter.search_zoekt is called directly without going through the NL pipeline."""
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=SAMPLE_RESULTS)
        with patch("gateway.gateway.classify_query", return_value="exact"), \
             patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import search
            result = await search("SystemServer", top_k=5)
            mock_adapter.search_zoekt.assert_called_once()
            assert result == SAMPLE_RESULTS

    async def test_nl_disabled_always_exact_path(self):
        """When NL_ENABLED=False, even if classify_query might return NL, the exact path is taken."""
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=SAMPLE_RESULTS)
        with patch("gateway.gateway.config") as mock_config, \
             patch("gateway.gateway.classify_query") as mock_classify, \
             patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            mock_config.NL_ENABLED = False
            from gateway.gateway import search
            result = await search("how does system server start")
            # classify_query is called, but the result is ignored when NL_ENABLED=False
            mock_adapter.search_zoekt.assert_called_once()
            assert result == SAMPLE_RESULTS

    async def test_nl_path_full_pipeline(self):
        """When query_type='natural_language', the full NL pipeline runs: rewrite → search → rrf → rerank."""
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
            # parallel multi-lane: search_zoekt should be called once per rewritten query (2 calls)
            assert mock_adapter.search_zoekt.call_count == 2
            assert isinstance(result, list)

    async def test_nl_empty_rewrite_fallback(self):
        """When rewrite_query returns an empty list, falls back to direct Zoekt search."""
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=SAMPLE_RESULTS)
        with patch("gateway.gateway.classify_query", return_value="natural_language"), \
             patch("gateway.gateway.rewrite_query", new=AsyncMock(return_value=[])), \
             patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import search
            result = await search("some query")
            # falls back to direct search
            mock_adapter.search_zoekt.assert_called_once()
            assert result == SAMPLE_RESULTS

    async def test_nl_all_routes_fail_fallback(self):
        """When all parallel routes fail, falls back to direct Zoekt search."""
        rewrite_output = [{"query": "q1"}, {"query": "q2"}]

        call_count = 0

        async def side_effect_search(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # first two calls (parallel routes, top_k=20) raise; third (fallback) succeeds
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
            # final fallback call succeeds
            assert result == SAMPLE_RESULTS

    async def test_score_threshold_filters_results(self):
        """score_threshold filters out results below the threshold (NL pipeline filters after rerank)."""
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
            # rrf_merge passes through original results, preserving scores
            mock_rrf.return_value = [high_score, low_score]
            # feature_rerank also passes through (preserving scores)
            mock_rerank.return_value = [high_score, low_score]
            from gateway.gateway import search
            result = await search("query", score_threshold=0.5)
            # score_threshold=0.5 filters out low_score; only high_score remains
            assert len(result) == 1
            assert result[0]["score"] >= 0.5


# ─── search_symbol() function tests ──────────────────────────────────────────

@pytest.mark.asyncio
class TestSearchSymbol:
    """Test suite for the search_symbol() function."""

    async def test_sym_prefix_added(self):
        """sym: prefix is automatically prepended to the search query."""
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=SAMPLE_RESULTS)
        with patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import search_symbol
            await search_symbol("SystemServer")
            call_kwargs = mock_adapter.search_zoekt.call_args[1]
            assert call_kwargs["query"] == "sym:SystemServer"

    async def test_sym_fallback_on_empty(self):
        """Falls back to plain search when sym: search returns no results."""
        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if "sym:" in kwargs.get("query", ""):
                return []  # sym: returns nothing
            return SAMPLE_RESULTS  # plain search has results

        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(side_effect=side_effect)
        with patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import search_symbol
            result = await search_symbol("SystemServer")
            assert call_count == 2  # called twice: sym: + plain
            assert result == SAMPLE_RESULTS

    async def test_sym_no_fallback_when_results_exist(self):
        """Does not trigger fallback when sym: search returns results."""
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=SAMPLE_RESULTS)
        with patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import search_symbol
            result = await search_symbol("SystemServer")
            assert mock_adapter.search_zoekt.call_count == 1
            assert result == SAMPLE_RESULTS


# ─── search_file() function tests ────────────────────────────────────────────

@pytest.mark.asyncio
class TestSearchFile:
    """Test suite for the search_file() function."""

    async def test_file_prefix_added(self):
        """file: prefix is automatically prepended to the search query."""
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=SAMPLE_RESULTS)
        with patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import search_file
            await search_file("SystemServer.java")
            call_kwargs = mock_adapter.search_zoekt.call_args[1]
            assert call_kwargs["query"] == "file:SystemServer.java"

    async def test_file_with_extra_query(self):
        """Extra query terms are appended after the file: prefix."""
        mock_adapter = MagicMock()
        mock_adapter.search_zoekt = AsyncMock(return_value=SAMPLE_RESULTS)
        with patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import search_file
            await search_file("SystemServer.java", extra_query="startBootstrap")
            call_kwargs = mock_adapter.search_zoekt.call_args[1]
            assert call_kwargs["query"] == "file:SystemServer.java startBootstrap"


# ─── search_regex() function tests ───────────────────────────────────────────

@pytest.mark.asyncio
class TestSearchRegex:
    """Test suite for the search_regex() function."""

    async def test_delegates_to_adapter_search_regex(self):
        """Delegates to the adapter's search_regex method."""
        mock_adapter = MagicMock()
        mock_adapter.search_regex = AsyncMock(return_value=SAMPLE_RESULTS)
        with patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import search_regex
            result = await search_regex(r"start\w+Services")
            mock_adapter.search_regex.assert_called_once()
            call_kwargs = mock_adapter.search_regex.call_args[1]
            assert call_kwargs["pattern"] == r"start\w+Services"
            assert result == SAMPLE_RESULTS


# ─── list_repos() function tests ─────────────────────────────────────────────

@pytest.mark.asyncio
class TestListRepos:
    """Test suite for the list_repos() function."""

    async def test_delegates_to_adapter_list_repos(self):
        """Delegates to the adapter's list_repos method."""
        repo_list = [{"name": "frameworks/base"}]
        mock_adapter = MagicMock()
        mock_adapter.list_repos = AsyncMock(return_value=repo_list)
        with patch("gateway.gateway._get_adapter", return_value=mock_adapter):
            from gateway.gateway import list_repos
            result = await list_repos(query="frameworks")
            mock_adapter.list_repos.assert_called_once_with(query="frameworks", top_k=50)
            assert result == repo_list


# ─── get_file_content() function tests ───────────────────────────────────────

@pytest.mark.asyncio
class TestGetFileContent:
    """Test suite for the get_file_content() function."""

    async def test_delegates_to_adapter_fetch_file_content(self):
        """Delegates to the adapter's fetch_file_content method."""
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
