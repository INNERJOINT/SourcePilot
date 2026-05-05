"""Tests: M2 — public /mcp endpoint exposed exactly once, no /mcp/mcp duplication.

The outer Starlette mounts the FastMCP app at "/" (not "/mcp"), because the inner
FastMCP app already exposes Route("/mcp"). Mounting at "/mcp" composed to "/mcp/mcp",
which broke clients. This test pins the working layout.
"""

import asyncio
import unittest.mock as mock

import entry.mcp_http as mcp_http_mod
import starlette.applications as _sa
from starlette.routing import Mount


def test_exactly_one_mcp_mount(monkeypatch):
    """Outer routes contain Mount('/'); the public /mcp endpoint comes from the inner app."""
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

    mounts = [r for r in captured_routes if isinstance(r, Mount)]
    # Starlette normalizes Mount("/") path to ""
    root_mounts = [r for r in mounts if r.path in ("", "/")]
    bad_mcp_mounts = [r for r in mounts if r.path in ("/mcp", "/mcp/")]

    assert len(root_mounts) == 1, f"Expected exactly 1 Mount('/'), got {len(root_mounts)}"
    assert len(bad_mcp_mounts) == 0, (
        f"Mount('/mcp') would compose with the inner Route('/mcp') to /mcp/mcp; "
        f"got {len(bad_mcp_mounts)} such mounts"
    )
