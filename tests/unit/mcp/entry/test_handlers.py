"""
MCP handlers unit tests.

Tests tool routing, filter extraction, result formatting, and other functionality
in entry/handlers.py.
"""

import httpx
import pytest
import respx
from entry.handlers import (
    SOURCEPILOT_URL,
    _extract_filters,
    _format_results,
    _handle_get_file_content,
    _handle_list_repos,
    _handle_search_code,
    call_tool,
    list_tools,
)
from mcp.types import TextContent

# ─── _extract_filters tests ───────────────────────────────

class TestExtractFilters:
    """Tests _extract_filters extracting filter fields from arguments."""

    def test_full_args(self):
        """All filter parameters present -> all extracted."""
        args = {"lang": "java", "branch": "main", "case_sensitive": "yes"}
        result = _extract_filters(args)
        assert result["lang"] == "java"
        assert result["branch"] == "main"
        assert result["case_sensitive"] == "yes"

    def test_partial_args(self):
        """Partial parameters -> missing fields return None."""
        args = {"lang": "python"}
        result = _extract_filters(args)
        assert result["lang"] == "python"
        assert result["branch"] is None
        assert result["case_sensitive"] == "auto"

    def test_empty_args(self):
        """Empty arguments -> lang/branch is None, case_sensitive is auto."""
        result = _extract_filters({})
        assert result["lang"] is None
        assert result["branch"] is None
        assert result["case_sensitive"] == "auto"

    def test_empty_string_becomes_none(self):
        """Empty-string lang/branch should be treated as None."""
        args = {"lang": "", "branch": ""}
        result = _extract_filters(args)
        assert result["lang"] is None
        assert result["branch"] is None


# ─── _format_results tests ────────────────────────────────

class TestFormatResults:
    """Tests _format_results formatting result list into text."""

    def test_with_results(self):
        """With results -> formatted text including location info."""
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
        assert "Found 1" in text
        assert "SystemServer" in text
        assert "frameworks/base" in text
        assert "L120-L125" in text
        assert "startBootstrapServices" in text

    def test_empty_list(self):
        """Empty results -> message containing 'No code found'."""
        text = _format_results("nonexistent_query", [])
        assert "No code found" in text
        assert "nonexistent_query" in text

    def test_multiple_results(self):
        """Multiple results -> numbered in order."""
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
        """content == '(no content preview available)' -> code block omitted."""
        results = [
            {
                "title": "A.java",
                "content": "(no content preview available)",
                "metadata": {"repo": "r", "path": "A.java"},
            }
        ]
        text = _format_results("q", results)
        assert "no content preview" not in text


# ─── list_tools tests ────────────────────────────────────

@pytest.mark.asyncio
async def test_list_tools_returns_seven():
    """list_tools should return 7 tools (6 search + list_projects)."""
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


# ─── call_tool routing tests ──────────────────────────────────

@pytest.mark.asyncio
async def test_call_tool_unknown():
    """Unknown tool name returns 'Unknown tool: ...' message."""
    result = await call_tool("invalid_tool", {})
    assert len(result) == 1
    assert isinstance(result[0], TextContent)
    assert "Unknown tool: invalid_tool" in result[0].text


@pytest.mark.asyncio
@respx.mock
async def test_call_tool_search_code_routes_correctly():
    """call_tool('search_code', ...) calls the correct SourcePilot endpoint."""
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
    """When _post raises, call_tool returns 'Tool error: ...' message."""
    respx.post(f"{SOURCEPILOT_URL}/api/search").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    result = await call_tool("search_code", {"query": "test"})
    assert len(result) == 1
    assert "Tool error" in result[0].text


# ─── _handle_search_code tests ────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_handle_search_code_builds_correct_body():
    """_handle_search_code builds a request body with query/repos/top_k/filters."""
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
    """Empty-string repo argument should be converted to None (no repo restriction)."""
    import json

    captured_body = {}

    def capture_request(request):
        captured_body.update(json.loads(request.content))
        return httpx.Response(200, json=[])

    respx.post(f"{SOURCEPILOT_URL}/api/search").mock(side_effect=capture_request)

    await _handle_search_code({"query": "test", "repo": ""}, "trace-456")

    assert captured_body["repos"] is None


# ─── _handle_list_repos tests ────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_handle_list_repos_empty_returns_not_found():
    """list_repos returning [] -> 'No matching repositories found' message."""
    respx.post(f"{SOURCEPILOT_URL}/api/list_repos").mock(
        return_value=httpx.Response(200, json=[])
    )

    result = await _handle_list_repos({}, "trace-000")
    assert len(result) == 1
    assert "No matching repositories found" in result[0].text


@pytest.mark.asyncio
@respx.mock
async def test_handle_list_repos_with_results():
    """list_repos returning a list -> formatted output."""
    respx.post(f"{SOURCEPILOT_URL}/api/list_repos").mock(
        return_value=httpx.Response(200, json=[
            {"name": "frameworks/base", "url": ""},
            {"name": "frameworks/av", "url": "https://example.com/av"},
        ])
    )

    result = await _handle_list_repos({}, "trace-001")
    assert "Found 2 repositories" in result[0].text
    assert "frameworks/base" in result[0].text
    assert "frameworks/av" in result[0].text


# ─── _handle_get_file_content tests ──────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_handle_get_file_content_formats_header():
    """get_file_content output includes a header with line range."""
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
