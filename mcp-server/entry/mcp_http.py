"""MCP Server — Streamable HTTP transport mode.

Preserves:
- BearerTokenMiddleware (required MCP_AUTH_TOKEN)
- /health bypass (no auth required)
- sys.exit(1) when MCP_AUTH_TOKEN is missing
- FastMCP lifespan-owned httpx.AsyncClient
"""

from __future__ import annotations

import logging
import os
import sys

import uvicorn
from mcp_server import mcp
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)


class BearerTokenMiddleware:
    """Bearer Token authentication middleware."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Pass lifespan events through (required for session_manager.run())
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Health probe bypasses auth
        if scope.get("path") == "/health":
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


async def main_streamable_http(host: str, port: int) -> None:
    """Run in Streamable HTTP mode."""
    logger.info("Starting AOSP Code Search MCP Server (streamable-http)")
    logger.info("Listening on http://%s:%d/mcp", host, port)

    auth_token = os.environ.get("MCP_AUTH_TOKEN", "").strip()
    if not auth_token:
        logger.error("MCP_AUTH_TOKEN required for streamable_http transport")
        sys.exit(1)
    logger.info("Bearer token authentication ENABLED")

    # FastMCP generates the Starlette app with its own lifespan (runs session_manager)
    # We wrap it with a custom Starlette that adds /health + BearerTokenMiddleware.
    mcp_app = mcp.streamable_http_app()

    async def health(request):  # noqa: ANN001, ANN202
        return JSONResponse({"status": "ok"})

    # Build outer Starlette that owns the /health route and mounts the FastMCP app.
    # Mount at "/" because the inner FastMCP app already exposes Route("/mcp"); mounting
    # at "/mcp" would compose to "/mcp/mcp". /health is matched first by route order.
    # Forward the inner app's lifespan so FastMCP's session_manager.run() actually starts;
    # without this, requests fail with "Task group is not initialized".
    outer = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Mount("/", app=mcp_app),
        ],
        lifespan=lambda app: mcp_app.router.lifespan_context(app),
    )

    wrapped = BearerTokenMiddleware(outer, auth_token)

    config = uvicorn.Config(app=wrapped, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()
