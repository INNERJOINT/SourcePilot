"""
MCP → SourcePilot 端到端测试

使用 Starlette TestClient 测试真实的 SourcePilot HTTP API。
MCP call_tool 层通过 respx 模拟 SourcePilot 响应，独立验证每一跳。
"""
import pytest
import respx
import httpx
from starlette.testclient import TestClient


# ─── SourcePilot TestClient 测试 ─────────────────────────

class TestSourcePilotHTTPAPI:
    """通过 TestClient 直接测试 SourcePilot HTTP API"""

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
        """POST /api/search 带 mock Zoekt → 返回搜索结果列表"""
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
        """POST /api/search 缺少 query 参数 → 400"""
        resp = self.client.post("/api/search", json={})
        assert resp.status_code == 400

    @respx.mock
    def test_search_empty_results(self):
        """Zoekt 返回空结果时，/api/search 返回空列表"""
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
        """POST /api/list_repos → 返回仓库列表"""
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
        """POST /api/search_symbol → 正常返回"""
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
        """POST /api/get_file_content 缺少 repo/filepath → 400"""
        resp = self.client.post("/api/get_file_content", json={"repo": "frameworks/base"})
        assert resp.status_code == 400


# ─── MCP call_tool → mock SourcePilot 链路测试 ──────────

class TestMCPCallToolChain:
    """测试 MCP call_tool 独立链路（respx mock SourcePilot）"""

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_code_via_call_tool(self):
        """call_tool('search_code') 向 SourcePilot /api/search POST 并返回格式化文本"""
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
        """call_tool('list_repos') 返回格式化仓库列表"""
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
        assert "2 个仓库" in text

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_file_content_via_call_tool(self):
        """call_tool('get_file_content') 返回带文件头的内容"""
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
        """SourcePilot 连接失败时，call_tool 返回中文错误提示"""
        from entry.handlers import call_tool, SOURCEPILOT_URL

        respx.post(f"{SOURCEPILOT_URL}/api/search").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        results = await call_tool("search_code", {"query": "test"})
        assert len(results) == 1
        assert "操作出错" in results[0].text

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_file_via_call_tool(self):
        """call_tool('search_file') 正确路由到 /api/search_file"""
        from entry.handlers import call_tool, SOURCEPILOT_URL

        respx.post(f"{SOURCEPILOT_URL}/api/search_file").mock(
            return_value=httpx.Response(200, json=[])
        )

        results = await call_tool("search_file", {"path": "SystemServer.java"})
        assert len(results) == 1
        # 空结果应包含 "未找到"
        assert "未找到" in results[0].text
