"""
BearerTokenMiddleware unit tests

Tests the authentication logic of BearerTokenMiddleware in entry/mcp_http.py.
"""
import pytest
from entry.mcp_http import BearerTokenMiddleware
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

# ─── Test inner app ────────────────────────────────────

async def hello(request):
    """Simple inner handler used to verify request passthrough."""
    return JSONResponse({"ok": True})


inner_app = Starlette(routes=[Route("/test", hello)])
TEST_TOKEN = "test-token-12345"
wrapped_app = BearerTokenMiddleware(inner_app, TEST_TOKEN)
client = TestClient(wrapped_app, raise_server_exceptions=True)


# ─── Auth success tests ────────────────────────────────

def test_valid_token_passes_through():
    """With a valid Bearer Token, request passes through to the inner app and returns 200."""
    resp = client.get("/test", headers={"Authorization": f"Bearer {TEST_TOKEN}"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


# ─── Auth failure tests ────────────────────────────────

def test_invalid_token_returns_401():
    """With a wrong Bearer Token, returns 401 with invalid_token error."""
    resp = client.get("/test", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "invalid_token"


def test_missing_auth_header_returns_401():
    """Without an Authorization header, returns 401 with unauthorized error."""
    resp = client.get("/test")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "unauthorized"


def test_non_bearer_prefix_returns_401():
    """With a non-Bearer Authorization prefix, returns 401."""
    resp = client.get("/test", headers={"Authorization": "Token some-api-key"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "unauthorized"


# ─── Non-HTTP scope passthrough tests ──────────────────

@pytest.mark.asyncio
async def test_lifespan_scope_bypasses_auth():
    """lifespan scope type should bypass auth and pass directly to the inner app."""
    call_log = []

    async def mock_inner(scope, receive, send):
        call_log.append(scope["type"])

    middleware = BearerTokenMiddleware(mock_inner, TEST_TOKEN)

    # Simulate lifespan scope (no headers)
    scope = {"type": "lifespan"}
    await middleware(scope, None, None)

    assert "lifespan" in call_log


@pytest.mark.asyncio
async def test_websocket_scope_bypasses_auth():
    """websocket scope type should bypass auth and pass directly to the inner app."""
    call_log = []

    async def mock_inner(scope, receive, send):
        call_log.append(scope["type"])

    middleware = BearerTokenMiddleware(mock_inner, TEST_TOKEN)

    # Simulate websocket scope
    scope = {"type": "websocket", "headers": []}
    await middleware(scope, None, None)

    assert "websocket" in call_log


# ─── WWW-Authenticate response header tests ─────────────────────────

def test_missing_token_has_www_authenticate_header():
    """When token is missing, response includes a WWW-Authenticate header."""
    resp = client.get("/test")
    assert "www-authenticate" in resp.headers or "WWW-Authenticate" in resp.headers


def test_invalid_token_has_www_authenticate_header():
    """When token is wrong, response includes a WWW-Authenticate header."""
    resp = client.get("/test", headers={"Authorization": "Bearer bad"})
    assert "www-authenticate" in resp.headers or "WWW-Authenticate" in resp.headers


# ─── /health health-check auth bypass ─────────────────────────────────

async def health(request):
    return JSONResponse({"status": "ok"})


_health_inner = Starlette(routes=[Route("/health", health), Route("/test", hello)])
_health_wrapped = BearerTokenMiddleware(_health_inner, TEST_TOKEN)
_health_client = TestClient(_health_wrapped)


def test_health_endpoint_bypasses_auth():
    """/health check does not require a Bearer token (for docker/k8s probes)."""
    resp = _health_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_endpoint_works_with_invalid_token():
    """/health passes even with a wrong token."""
    resp = _health_client.get("/health", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 200


def test_non_health_still_requires_auth():
    """Non-/health paths still require authentication."""
    resp = _health_client.get("/test")
    assert resp.status_code == 401
