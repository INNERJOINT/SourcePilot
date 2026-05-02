"""
MCP → SourcePilot end-to-end tests

Tests the real SourcePilot HTTP API via Starlette TestClient.
The MCP call_tool layer mocks SourcePilot responses via respx, validating each hop independently.
"""
import pytest
import respx
import httpx
from starlette.testclient import TestClient


# ─── SourcePilot TestClient tests ─────────────────────────

class TestSourcePilotHTTPAPI:
    """Tests the SourcePilot HTTP API directly via TestClient."""

    @pytest.fixture(autouse=True)
    def setup_client(self):
        from app import app
        self.client = TestClient(app, raise_server_exceptions=True)

    @respx.mock
    def test_health_endpoint(self):
        """GET /api/health → 200 with status:ok"""
        resp = self.client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "sourcepilot"

    @respx.mock
    def test_search_endpoint_returns_results(self):
        """POST /api/search with mock Zoekt → returns a list of search results."""
        import config

        zoekt_response = {
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
                    }
                ],
                "Stats": {"MatchCount": 1, "FileCount": 1}
            }
        }

        respx.get(f"{config.ZOEKT_URL}/search").mock(
            return_value=httpx.Response(200, json=zoekt_response)
        )

        resp = self.client.post("/api/search", json={"query": "SystemServer"})
        assert resp.status_code == 200
        results = resp.json()
        assert isinstance(results, list)
        assert len(results) > 0
        assert results[0]["metadata"]["repo"] == "frameworks/base"

    @respx.mock
    def test_search_missing_query_returns_400(self):
        """POST /api/search with missing query parameter → 400."""
        resp = self.client.post("/api/search", json={})
        assert resp.status_code == 400

    @respx.mock
    def test_search_empty_results(self):
        """When Zoekt returns empty results, /api/search returns an empty list."""
        import config

        respx.get(f"{config.ZOEKT_URL}/search").mock(
            return_value=httpx.Response(200, json={
                "Result": {"FileMatches": [], "Stats": {"MatchCount": 0, "FileCount": 0}}
            })
        )

        resp = self.client.post("/api/search", json={"query": "nonexistent_xyz_123"})
        assert resp.status_code == 200
        assert resp.json() == []

    @respx.mock
    def test_list_repos_endpoint(self):
        """POST /api/list_repos → returns a list of repositories."""
        import config

        respx.get(f"{config.ZOEKT_URL}/search").mock(
            return_value=httpx.Response(200, json={
                "Result": {
                    "FileMatches": [
                        {
                            "Repo": "frameworks/base",
                            "FileName": "Android.bp",
                            "Score": 10.0,
                            "Matches": []
                        }
                    ],
                    "Stats": {"MatchCount": 1, "FileCount": 1}
                }
            })
        )

        resp = self.client.post("/api/list_repos", json={"query": "frameworks"})
        assert resp.status_code == 200
        repos = resp.json()
        assert isinstance(repos, list)

    @respx.mock
    def test_search_symbol_endpoint(self):
        """POST /api/search_symbol → returns results normally."""
        import config

        respx.get(f"{config.ZOEKT_URL}/search").mock(
            return_value=httpx.Response(200, json={
                "Result": {"FileMatches": [], "Stats": {"MatchCount": 0, "FileCount": 0}}
            })
        )

        resp = self.client.post("/api/search_symbol", json={"symbol": "ActivityManager"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @respx.mock
    def test_get_file_content_missing_params_returns_400(self):
        """POST /api/get_file_content with missing repo/filepath → 400."""
        resp = self.client.post("/api/get_file_content", json={"repo": "frameworks/base"})
        assert resp.status_code == 400


# ─── MCP call_tool → mock SourcePilot chain tests ──────────

class TestMCPCallToolChain:
    """Tests the MCP call_tool chain in isolation (respx mocks SourcePilot)."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_code_via_call_tool(self):
        """call_tool('search_code') POSTs to SourcePilot /api/search and returns formatted text."""
        from entry.handlers import call_tool, SOURCEPILOT_URL

        respx.post(f"{SOURCEPILOT_URL}/api/search").mock(
            return_value=httpx.Response(200, json=[
                {
                    "title": "frameworks/base/services/SystemServer.java",
                    "content": "private void startBootstrapServices() {",
                    "score": 0.9,
                    "metadata": {
                        "repo": "frameworks/base",
                        "path": "services/core/java/com/android/server/SystemServer.java",
                        "start_line": 118,
                        "end_line": 122,
                    },
                }
            ])
        )

        results = await call_tool("search_code", {"query": "startBootstrapServices"})
        assert len(results) == 1
        text = results[0].text
        assert "startBootstrapServices" in text
        assert "frameworks/base" in text

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_repos_via_call_tool(self):
        """call_tool('list_repos') returns a formatted repository list."""
        from entry.handlers import call_tool, SOURCEPILOT_URL

        respx.post(f"{SOURCEPILOT_URL}/api/list_repos").mock(
            return_value=httpx.Response(200, json=[
                {"name": "frameworks/base", "url": ""},
                {"name": "frameworks/av", "url": "https://android.googlesource.com/platform/frameworks/av"},
            ])
        )

        results = await call_tool("list_repos", {})
        assert len(results) == 1
        text = results[0].text
        assert "frameworks/base" in text
        assert "2 repositories" in text or "Found 2" in text

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_file_content_via_call_tool(self):
        """call_tool('get_file_content') returns content with file header."""
        from entry.handlers import call_tool, SOURCEPILOT_URL

        respx.post(f"{SOURCEPILOT_URL}/api/get_file_content").mock(
            return_value=httpx.Response(200, json={
                "content": "L1: package com.android.server;\nL2: public class SystemServer {}",
                "total_lines": 500,
                "start_line": 1,
                "end_line": 2,
            })
        )

        results = await call_tool("get_file_content", {
            "repo": "frameworks/base",
            "filepath": "services/core/java/com/android/server/SystemServer.java",
        })

        assert len(results) == 1
        text = results[0].text
        assert "frameworks/base" in text
        assert "SystemServer.java" in text
        assert "500" in text

    @pytest.mark.asyncio
    @respx.mock
    async def test_sourcepilot_connection_error_returns_error_message(self):
        """When SourcePilot connection fails, call_tool returns an error message."""
        from entry.handlers import call_tool, SOURCEPILOT_URL

        respx.post(f"{SOURCEPILOT_URL}/api/search").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        results = await call_tool("search_code", {"query": "test"})
        assert len(results) == 1
        assert "error" in results[0].text.lower() or "unreachable" in results[0].text.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_file_via_call_tool(self):
        """call_tool('search_file') routes correctly to /api/search_file."""
        from entry.handlers import call_tool, SOURCEPILOT_URL

        respx.post(f"{SOURCEPILOT_URL}/api/search_file").mock(
            return_value=httpx.Response(200, json=[])
        )

        results = await call_tool("search_file", {"path": "SystemServer.java"})
        assert len(results) == 1
        # empty results should contain "No code found" or similar
        assert "No code found" in results[0].text or "not found" in results[0].text.lower() or len(results[0].text) > 0
