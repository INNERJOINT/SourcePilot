"""MCP Server — stdio transport mode."""

import asyncio
import logging
import sys

from mcp_server import mcp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


async def main_stdio() -> None:
    """Run in stdio mode (for Claude Code / local tool use)."""
    logger.info("Starting AOSP Code Search MCP Server (stdio)")
    await mcp.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(main_stdio())
