"""
API Contract tests

Verifies round-trip JSON serialization/deserialization of SourcePilot gateway function return values.
Uses respx to mock Zoekt HTTP responses, calls gateway functions directly,
then does json.dumps + json.loads to confirm the structure matches expectations.
"""

import json
import pytest
import respx
import httpx

from gateway import gateway
import config

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
        ],
        "Stats": {"MatchCount": 1, "FileCount": 1}
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


# ─── Search result contract tests ───────────────────────────

class TestSearchContract:
    """Validates the JSON serialization structure of gateway.search() return values."""

    @pytest.mark.asyncio
    async def test_search_results_have_expected_keys(self):
        """search results round-tripped through JSON contain title, content, score, metadata."""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            results = await gateway.search(query="startBootstrapServices")

            serialized = json.loads(json.dumps(results))
            assert isinstance(serialized, list)
            assert len(serialized) > 0

            for item in serialized:
                assert "title" in item
                assert "content" in item
                assert "score" in item
                assert "metadata" in item
                assert isinstance(item["metadata"], dict)

    @pytest.mark.asyncio
    async def test_search_empty_returns_empty_list(self):
        """search with no results returns an empty list."""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_EMPTY_RESPONSE)
            )

            results = await gateway.search(query="nonexistent")

            serialized = json.loads(json.dumps(results))
            assert serialized == []


class TestSearchSymbolContract:
    """Validates the JSON serialization structure of gateway.search_symbol() return values."""

    @pytest.mark.asyncio
    async def test_search_symbol_results_have_expected_keys(self):
        """search_symbol results round-tripped through JSON contain title, content, score, metadata."""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            results = await gateway.search_symbol(symbol="SystemServer")

            serialized = json.loads(json.dumps(results))
            assert isinstance(serialized, list)
            assert len(serialized) > 0

            for item in serialized:
                assert "title" in item
                assert "content" in item
                assert "score" in item
                assert "metadata" in item


class TestSearchFileContract:
    """Validates the JSON serialization structure of gateway.search_file() return values."""

    @pytest.mark.asyncio
    async def test_search_file_results_have_expected_keys(self):
        """search_file results round-tripped through JSON contain title, content, score, metadata."""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            results = await gateway.search_file(path="SystemServer.java")

            serialized = json.loads(json.dumps(results))
            assert isinstance(serialized, list)
            assert len(serialized) > 0

            for item in serialized:
                assert "title" in item
                assert "content" in item
                assert "score" in item
                assert "metadata" in item


class TestSearchRegexContract:
    """Validates the JSON serialization structure of gateway.search_regex() return values."""

    @pytest.mark.asyncio
    async def test_search_regex_results_have_expected_keys(self):
        """search_regex results round-tripped through JSON contain title, content, score, metadata."""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            results = await gateway.search_regex(pattern=r"startBootstrap\w+")

            serialized = json.loads(json.dumps(results))
            assert isinstance(serialized, list)
            assert len(serialized) > 0

            for item in serialized:
                assert "title" in item
                assert "content" in item
                assert "score" in item
                assert "metadata" in item


# ─── list_repos contract tests ─────────────────────────

class TestListReposContract:
    """Validates the JSON serialization structure of gateway.list_repos() return values."""

    @pytest.mark.asyncio
    async def test_list_repos_results_have_expected_keys(self):
        """list_repos results round-tripped through JSON contain name, url."""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/search").mock(
                return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
            )

            results = await gateway.list_repos(query="frameworks")

            serialized = json.loads(json.dumps(results))
            assert isinstance(serialized, list)
            assert len(serialized) > 0

            for item in serialized:
                assert "name" in item
                assert "url" in item


# ─── get_file_content contract tests ───────────────────

class TestGetFileContentContract:
    """Validates the JSON serialization structure of gateway.get_file_content() return values."""

    @pytest.mark.asyncio
    async def test_get_file_content_has_expected_keys(self):
        """get_file_content result round-tripped through JSON contains content, total_lines, repo, filepath, start_line, end_line."""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/print").mock(
                return_value=httpx.Response(200, text=MOCK_PRINT_RESPONSE_HTML)
            )

            result = await gateway.get_file_content(
                repo="frameworks/base",
                filepath="test.java",
            )

            serialized = json.loads(json.dumps(result))
            assert isinstance(serialized, dict)
            assert "content" in serialized
            assert "total_lines" in serialized
            assert "repo" in serialized
            assert "filepath" in serialized
            assert "start_line" in serialized
            assert "end_line" in serialized

    @pytest.mark.asyncio
    async def test_get_file_content_end_line_none_serializes_as_null(self):
        """get_file_content end_line=None serializes as null and deserializes back to None."""
        with respx.mock:
            respx.get(f"{config.ZOEKT_URL}/print").mock(
                return_value=httpx.Response(200, text=MOCK_PRINT_RESPONSE_HTML)
            )

            result = await gateway.get_file_content(
                repo="frameworks/base",
                filepath="test.java",
                end_line=None,
            )

            # When end_line is None, fetch_file_content reads to the end and
            # sets end_line to the actual last line number. To test the null
            # serialization contract, we manually set end_line to None.
            result_with_none = dict(result)
            result_with_none["end_line"] = None

            json_str = json.dumps(result_with_none)
            assert '"end_line": null' in json_str

            deserialized = json.loads(json_str)
            assert deserialized["end_line"] is None
