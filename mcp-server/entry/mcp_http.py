"""MCP Server — Streamable HTTP transport mode."""

import asyncio
import contextlib
import logging
import os

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from entry.handlers import server

logger = logging.getLogger(__name__)


class BearerTokenMiddleware:
    """Bearer Token 鉴权中间件"""

    def __init__(self, app: ASGIApp, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        # lifespan 事件必须透传给内层 app（触发 session_manager.run()）
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()

        if not auth_header.startswith("Bearer "):
            response = JSONResponse(
                {"error": "unauthorized", "error_description": "Missing Bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="mcp"'},
            )
            await response(scope, receive, send)
            return

        if auth_header[7:] != self.token:
            response = JSONResponse(
                {"error": "invalid_token", "error_description": "Invalid Bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


async def main_streamable_http(host: str, port: int):
    """以 Streamable HTTP 模式启动（供远程客户端通过 HTTP 访问）"""
    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    logger.info("Starting AOSP Code Search MCP Server (streamable-http)")
    logger.info("Listening on http://%s:%d/mcp", host, port)

    auth_token = os.getenv("MCP_AUTH_TOKEN", "")
    if auth_token:
        logger.info("Bearer token authentication ENABLED")
    else:
        logger.warning("Bearer token authentication DISABLED (set MCP_AUTH_TOKEN to enable)")

    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=False,
        stateless=False,
    )

    async def handle_mcp(scope, receive, send):
        await session_manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with session_manager.run():
            logger.info("MCP Session Manager running")
            yield

    app = Starlette(
        lifespan=lifespan,
        routes=[
            Mount("/mcp", app=handle_mcp),
            Mount("/mcp/", app=handle_mcp),
        ],
    )

    if auth_token:
        app = BearerTokenMiddleware(app, auth_token)

    uvicorn_config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="info",
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)
    await uvicorn_server.serve()
