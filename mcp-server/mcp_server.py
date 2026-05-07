"""MCP Server — FastMCP instance, lifespan, and tool/resource registration."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logger = logging.getLogger(__name__)

# ─── Lifespan context ──────────────────────────────────────────────────────────


@dataclass
class AppContext:
    """Lifespan-owned resources; access via ctx.request_context.lifespan_context."""

    http_client: httpx.AsyncClient


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[AppContext]:  # noqa: ARG001
    """Create and tear down the shared httpx client."""
    from entry.resources import set_resource_client

    client = httpx.AsyncClient(timeout=30.0)
    set_resource_client(client)
    logger.info("httpx.AsyncClient created (lifespan start)")
    try:
        yield AppContext(http_client=client)
    finally:
        await client.aclose()
        logger.info("httpx.AsyncClient closed (lifespan end)")


# ─── FastMCP instance ──────────────────────────────────────────────────────────

mcp: FastMCP[AppContext] = FastMCP(
    "sourcepilot-mcp",
    lifespan=_lifespan,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# ─── Register tools, prompts, resources ───────────────────────────────────────

from entry.tools import register_tools  # noqa: E402

register_tools(mcp)

from entry.resources import register_resources  # noqa: E402

register_resources(mcp)

from entry.prompts import register_prompts  # noqa: E402

register_prompts(mcp)

from entry.completions import register_completions  # noqa: E402

register_completions(mcp)

# ─── CLI entry point ───────────────────────────────────────────────────────────


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="AOSP Code Search MCP Server")
    parser.add_argument(
        "--transport",
        "-t",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport mode: stdio (default) or streamable-http",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Streamable HTTP listen address")
    parser.add_argument("--port", "-p", type=int, default=8888, help="Streamable HTTP listen port")
    args = parser.parse_args()

    if args.transport == "streamable-http":
        from entry.mcp_http import main_streamable_http

        asyncio.run(main_streamable_http(args.host, args.port))
    else:
        from entry.mcp_stdio import main_stdio

        asyncio.run(main_stdio())


if __name__ == "__main__":
    main()
