"""
BearerTokenMiddleware edge-case characterization tests.

These tests document the *current* behaviour of BearerTokenMiddleware so that
future refactors don't accidentally change semantics without visibility.
"""

import pytest
from entry.mcp_http import BearerTokenMiddleware
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

TEST_TOKEN = "secret-token"


async def _ok(request):  # noqa: ANN001, ANN202
    return JSONResponse({"ok": True})


_inner = Starlette(routes=[Route("/health", _ok), Route("/api", _ok)])
_wrapped = BearerTokenMiddleware(_inner, TEST_TOKEN)
_client = TestClient(_wrapped, raise_server_exceptions=True)


# ── Lowercase "bearer " prefix ────────────────────────────────────────────────


def test_lowercase_bearer_prefix_returns_401():
    """Lowercase 'bearer ' prefix is rejected (current behaviour).

    # TODO(#NNN): RFC 6750 — make Bearer scheme case-insensitive
    """
    resp = _client.get("/api", headers={"Authorization": f"bearer {TEST_TOKEN}"})
    assert resp.status_code == 401


# ── Empty token after "Bearer " prefix ───────────────────────────────────────


def test_bearer_empty_token_returns_401():
    """'Bearer ' with nothing after the space → invalid_token."""
    resp = _client.get("/api", headers={"Authorization": "Bearer "})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "invalid_token"


# ── Extra whitespace between "Bearer" and token ───────────────────────────────


def test_bearer_double_space_returns_401():
    """'Bearer  TOKEN' (two spaces) → 401 current behaviour (no whitespace trimming)."""
    resp = _client.get("/api", headers={"Authorization": f"Bearer  {TEST_TOKEN}"})
    assert resp.status_code == 401


# ── Non-HTTP scope passes through middleware ──────────────────────────────────


@pytest.mark.asyncio
async def test_lifespan_scope_passes_through():
    """lifespan scope must bypass auth so FastMCP session_manager can start."""
    received: list[str] = []

    async def fake_app(scope, receive, send):  # noqa: ANN001, ANN202
        received.append(scope["type"])

    mw = BearerTokenMiddleware(fake_app, TEST_TOKEN)
    await mw({"type": "lifespan"}, None, None)

    assert received == ["lifespan"]


# ── /health bypasses auth ─────────────────────────────────────────────────────


def test_health_no_auth_returns_200():
    """/health must respond 200 without any Authorization header."""
    resp = _client.get("/health")
    assert resp.status_code == 200
