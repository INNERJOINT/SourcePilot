"""
ZoektAdapter unit tests

Uses respx to mock Zoekt HTTP responses; no real Zoekt service required.
Covers search, regex search, repo listing, file content fetching, and snippet building.
"""

import json
import math
import pytest
import respx
import httpx

from adapters.zoekt import ZoektAdapter
import config

# Create a module-level adapter for backward-compat test access
_default_adapter = ZoektAdapter(zoekt_url=config.ZOEKT_URL)


class _ZoektClientCompat:
    """Shim to let tests use zoekt_client.search(...) style calls."""
    async def search(self, *a, **kw): return await _default_adapter.search_zoekt(*a, **kw)
    async def search_regex(self, *a, **kw): return await _default_adapter.search_regex(*a, **kw)
    async def list_repos(self, *a, **kw): return await _default_adapter.list_repos(*a, **kw)
    async def fetch_file_content(self, *a, **kw): return await _default_adapter.fetch_file_content(*a, **kw)
    def _build_content_snippet(self, *a, **kw): return _default_adapter._build_content_snippet(*a, **kw)

zoekt_client = _ZoektClientCompat()


# ─── Mock data ────────────────────────────────────────

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


# ─── zoekt_client.search() tests ──────────────────────

class TestSearch:
    """Tests for the zoekt_client.search() function."""

    @pytest.mark.asyncio
    async def test_basic_search(self):
        """Basic search returns records with the expected structure."""
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
        """repo filter parameter is included correctly in the query."""
        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await zoekt_client.search(query="test", repos="frameworks/base")

            # verify the query includes the r: prefix
            request = route.calls[0].request
            q_param = str(request.url.params.get("q", ""))
            assert "r:frameworks/base" in q_param

    @pytest.mark.asyncio
    async def test_search_with_lang_filter(self):
        """lang filter parameter is included correctly in the query."""
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
        """branch filter parameter is included correctly in the query."""
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
        """case_sensitive parameter is included correctly in the query."""
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
        """case_sensitive='auto' should not add a case: prefix to the query."""
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
        """Multiple filters can be combined together."""
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
        """Zoekt returns empty results."""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_EMPTY_RESPONSE)
            )

            results = await zoekt_client.search(query="nonexistent_symbol")
            assert results == []

    @pytest.mark.asyncio
    async def test_search_418_teapot(self):
        """Zoekt returning 418 indicates no results."""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(418, text="I'm a teapot")
            )

            results = await zoekt_client.search(query="nothing")
            assert results == []

    @pytest.mark.asyncio
    async def test_search_score_normalization_with_zoekt_score(self):
        """When a Score field is present, sigmoid normalization is applied."""
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
        """score_threshold filters out low-scoring results."""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            results = await zoekt_client.search(query="test", score_threshold=0.99)
            # both results' normalized scores should be below 0.99
            assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_top_k(self):
        """top_k limits the number of returned results."""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            results = await zoekt_client.search(query="test", top_k=1)
            assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_context_lines_param(self):
        """When NUM_CONTEXT_LINES > 0, the ctx parameter should be sent."""
        with respx.mock:
            route = respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            await zoekt_client.search(query="test")

            request = route.calls[0].request
            ctx_param = request.url.params.get("ctx", "")
            if config.NUM_CONTEXT_LINES > 0:
                assert ctx_param == str(config.NUM_CONTEXT_LINES)


# ─── zoekt_client.search_regex() tests ────────────────

class TestSearchRegex:
    """Tests for the zoekt_client.search_regex() function."""

    @pytest.mark.asyncio
    async def test_regex_query_format(self):
        """Regex search uses content:/pattern/ format."""
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
        """Regex search supports lang filter."""
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
        """Regex search supports repo filter."""
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


# ─── zoekt_client.list_repos() tests ──────────────────

class TestListRepos:
    """Tests for the zoekt_client.list_repos() function."""

    @pytest.mark.asyncio
    async def test_list_repos_query(self):
        """list_repos uses type:repo query."""
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
        """Without a query, only type:repo is used."""
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
        """list_repos extracts deduplicated repos from FileMatches."""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            repos = await zoekt_client.list_repos()

            # both MOCK records are frameworks/base; after dedup only 1 remains
            assert len(repos) == 1
            assert repos[0]["name"] == "frameworks/base"

    @pytest.mark.asyncio
    async def test_list_repos_empty(self):
        """Returns an empty list when there are no matching repos."""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(418, text="I'm a teapot")
            )

            repos = await zoekt_client.list_repos()
            assert repos == []


# ─── zoekt_client.fetch_file_content() tests ──────────

class TestFetchFileContent:
    """Tests for the zoekt_client.fetch_file_content() function."""

    @pytest.mark.asyncio
    async def test_fetch_full_file(self):
        """Fetch full file content."""
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
        """Fetch a specific line range."""
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
            # should contain exactly 3 lines
            lines = result["content"].split("\n")
            assert len(lines) == 3

    @pytest.mark.asyncio
    async def test_fetch_file_not_found(self):
        """Raises FileNotFoundError when the file does not exist."""
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
        """Output includes line number prefixes."""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/print").mock(
                return_value=httpx.Response(200, text=MOCK_PRINT_RESPONSE_HTML)
            )

            result = await zoekt_client.fetch_file_content(
                repo="test", filepath="test.java"
            )

            assert "L1:" in result["content"]
            assert "L5:" in result["content"]


# ─── _build_content_snippet() tests ───────────────────

class TestBuildContentSnippet:
    """Tests for code snippet building."""

    def test_normal_fragments(self):
        """Normal fragments are concatenated correctly."""
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
        """Returns placeholder text when there are no matches."""
        result = zoekt_client._build_content_snippet({"Matches": []})
        assert result == "(no content preview available)"

    def test_multiple_matches(self):
        """Multiple line matches."""
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
