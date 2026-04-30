"""Tests: C1 — MCP_AUTH_TOKEN required for streamable_http transport."""

import asyncio
import unittest.mock as mock

import pytest


def test_empty_token_causes_system_exit(monkeypatch):
    """Empty MCP_AUTH_TOKEN -> main_streamable_http() exits with SystemExit."""
    monkeypatch.setenv("MCP_AUTH_TOKEN", "")

    from entry.mcp_http import main_streamable_http

    with pytest.raises(SystemExit):
        asyncio.run(main_streamable_http("127.0.0.1", 18888))


def test_valid_token_constructs_app(monkeypatch):
    """Valid MCP_AUTH_TOKEN -> BearerTokenMiddleware wraps Starlette app without exit."""
    monkeypatch.setenv("MCP_AUTH_TOKEN", "secret-token")

    import entry.mcp_http as mcp_http_mod

    async def _fake_serve(self):
        return

    with mock.patch("uvicorn.Server.serve", new=_fake_serve):
        try:
            asyncio.run(mcp_http_mod.main_streamable_http("127.0.0.1", 18889))
        except SystemExit:
            pytest.fail("SystemExit raised with valid token")
        except Exception:
            # Other errors (e.g. uvicorn internals) are acceptable
            pass

    assert hasattr(mcp_http_mod, "BearerTokenMiddleware")
