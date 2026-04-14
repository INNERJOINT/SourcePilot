"""MCP Server — stdio transport mode."""

import asyncio
import logging

from entry.handlers import server

logger = logging.getLogger(__name__)


async def main_stdio():
    """以 stdio 模式启动（供 Claude Code 等本地工具直接调用）"""
    from mcp.server.stdio import stdio_server

    logger.info("Starting AOSP Code Search MCP Server (stdio)")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main_stdio())
