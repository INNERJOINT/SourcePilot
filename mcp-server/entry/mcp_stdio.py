"""MCP Server — stdio transport mode."""

import asyncio
import logging

import httpx

from entry.handlers import _set_http_client, server

logger = logging.getLogger(__name__)


async def main_stdio():
    """以 stdio 模式启动（供 Claude Code 等本地工具直接调用）"""
    from mcp.server.stdio import stdio_server

    logger.info("Starting AOSP Code Search MCP Server (stdio)")

    client = httpx.AsyncClient(timeout=30.0)
    _set_http_client(client)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main_stdio())
