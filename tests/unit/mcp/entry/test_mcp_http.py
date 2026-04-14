"""
BearerTokenMiddleware 单元测试

测试 entry/mcp_http.py 中 BearerTokenMiddleware 的鉴权逻辑。
"""
import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from entry.mcp_http import BearerTokenMiddleware

# ─── 测试用 inner app ────────────────────────────────────

async def hello(request):
    """简单的内层 handler，用于验证请求是否透传"""
    return JSONResponse({"ok": True})


inner_app = Starlette(routes=[Route("/test", hello)])
TEST_TOKEN = "test-token-12345"
wrapped_app = BearerTokenMiddleware(inner_app, TEST_TOKEN)
client = TestClient(wrapped_app, raise_server_exceptions=True)


# ─── 鉴权成功测试 ────────────────────────────────────────

def test_valid_token_passes_through():
    """携带正确 Bearer Token 时，请求透传到内层 app，返回 200"""
    resp = client.get("/test", headers={"Authorization": f"Bearer {TEST_TOKEN}"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


# ─── 鉴权失败测试 ────────────────────────────────────────

def test_invalid_token_returns_401():
    """携带错误 Bearer Token 时，返回 401 及 invalid_token 错误"""
    resp = client.get("/test", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "invalid_token"


def test_missing_auth_header_returns_401():
    """未携带 Authorization 头时，返回 401 及 unauthorized 错误"""
    resp = client.get("/test")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "unauthorized"


def test_non_bearer_prefix_returns_401():
    """Authorization 头非 Bearer 前缀时，返回 401"""
    resp = client.get("/test", headers={"Authorization": "Token some-api-key"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "unauthorized"


# ─── 非 HTTP scope 透传测试 ──────────────────────────────

@pytest.mark.asyncio
async def test_lifespan_scope_bypasses_auth():
    """lifespan scope 类型应绕过鉴权，直接透传给内层 app"""
    call_log = []

    async def mock_inner(scope, receive, send):
        call_log.append(scope["type"])

    middleware = BearerTokenMiddleware(mock_inner, TEST_TOKEN)

    # 模拟 lifespan scope（无 headers）
    scope = {"type": "lifespan"}
    await middleware(scope, None, None)

    assert "lifespan" in call_log


@pytest.mark.asyncio
async def test_websocket_scope_bypasses_auth():
    """websocket scope 类型应绕过鉴权，直接透传给内层 app"""
    call_log = []

    async def mock_inner(scope, receive, send):
        call_log.append(scope["type"])

    middleware = BearerTokenMiddleware(mock_inner, TEST_TOKEN)

    # 模拟 websocket scope
    scope = {"type": "websocket", "headers": []}
    await middleware(scope, None, None)

    assert "websocket" in call_log


# ─── WWW-Authenticate 响应头测试 ─────────────────────────

def test_missing_token_has_www_authenticate_header():
    """缺少 token 时，响应包含 WWW-Authenticate 头"""
    resp = client.get("/test")
    assert "www-authenticate" in resp.headers or "WWW-Authenticate" in resp.headers


def test_invalid_token_has_www_authenticate_header():
    """token 错误时，响应包含 WWW-Authenticate 头"""
    resp = client.get("/test", headers={"Authorization": "Bearer bad"})
    assert "www-authenticate" in resp.headers or "WWW-Authenticate" in resp.headers
