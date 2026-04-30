"""Tests: M2 — exactly one Mount with path '/mcp' in the Starlette app."""

import asyncio
import unittest.mock as mock

import entry.mcp_http as mcp_http_mod
import starlette.applications as _sa
from starlette.routing import Mount


def test_exactly_one_mcp_mount(monkeypatch):
    """Only one Mount('/mcp') exists; no duplicate Mount('/mcp/')."""
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")

    captured_routes = []

    def patched_init(self, **kwargs):
        captured_routes.extend(kwargs.get("routes", []))
        self.router = mock.MagicMock()
        self.middleware_stack = None
        self.state = mock.MagicMock()

    with mock.patch.object(_sa.Starlette, "__init__", patched_init), \
         mock.patch("uvicorn.Server.serve", side_effect=KeyboardInterrupt):
        try:
            asyncio.run(mcp_http_mod.main_streamable_http("127.0.0.1", 19000))
        except (SystemExit, KeyboardInterrupt, Exception):
            pass

    mcp_mounts = [
        r for r in captured_routes
        if isinstance(r, Mount) and r.path in ("/mcp", "/mcp/")
    ]
    mcp_exact = [r for r in mcp_mounts if r.path == "/mcp"]
    mcp_slash = [r for r in mcp_mounts if r.path == "/mcp/"]

    assert len(mcp_exact) == 1, f"Expected exactly 1 Mount('/mcp'), got {len(mcp_exact)}"
    assert len(mcp_slash) == 0, f"Expected 0 Mount('/mcp/'), got {len(mcp_slash)}"
