"""Entry point -- `python -m mcp_server`."""
import asyncio
import argparse

# Re-export for backward compat (tests import call_tool, server from here)
from entry.handlers import call_tool, server  # noqa: F401


def main():
    parser = argparse.ArgumentParser(description="AOSP Code Search MCP Server")
    parser.add_argument(
        "--transport", "-t",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="传输模式: stdio（默认，本地工具调用）或 streamable-http（远程 HTTP 访问）",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Streamable HTTP 监听地址（默认 0.0.0.0）",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8888,
        help="Streamable HTTP 监听端口（默认 8888）",
    )
    args = parser.parse_args()

    if args.transport == "streamable-http":
        from entry.mcp_http import main_streamable_http
        asyncio.run(main_streamable_http(args.host, args.port))
    else:
        from entry.mcp_stdio import main_stdio
        asyncio.run(main_stdio())


if __name__ == "__main__":
    main()
