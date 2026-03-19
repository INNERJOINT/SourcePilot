"""
AOSP Code Search MCP Server

通过 MCP (Model Context Protocol) 暴露 Zoekt 代码搜索能力，
支持 Claude Code、Cursor、Windsurf、Cline 等 AI 编码工具。

启动方式:
  python mcp_server.py                   # stdio 模式（默认，供 Claude Code 等直接调用）
  python mcp_server.py --transport sse   # SSE 模式（远程访问）
"""

import asyncio
import json
import logging
import sys
import os

# 确保能 import 本地模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

import config
import zoekt_client

# 日志配置（MCP stdio 模式下日志必须输出到 stderr）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ─── 创建 MCP Server ──────────────────────────────────

server = Server("aosp-code-search")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """声明可用的工具列表。"""
    return [
        Tool(
            name="search_code",
            description=(
                "搜索 AOSP 代码库。支持关键词、类名、函数名、文件路径、属性名等。"
                "返回匹配的代码片段及其文件位置。"
                "示例: search_code(query='SystemServer startBootstrapServices')"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询。可以是关键词、符号名、文件路径、属性名等",
                    },
                    "repo": {
                        "type": "string",
                        "description": "可选，限定搜索的 repo 名称前缀（如 frameworks/base）",
                        "default": "",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量，默认 10",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="search_symbol",
            description=(
                "精确搜索代码符号（类名、函数名、变量名）。"
                "使用 Zoekt 的 sym: 前缀进行符号搜索。"
                "示例: search_symbol(symbol='startBootstrapServices')"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "要搜索的符号名（类名、函数名等）",
                    },
                    "repo": {
                        "type": "string",
                        "description": "可选，限定搜索的 repo",
                        "default": "",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量，默认 5",
                        "default": 5,
                    },
                },
                "required": ["symbol"],
            },
        ),
        Tool(
            name="search_file",
            description=(
                "按文件名或路径搜索代码文件。"
                "使用 Zoekt 的 file: 前缀进行文件搜索。"
                "示例: search_file(path='SystemServer.java')"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件名或路径模式（如 SystemServer.java 或 frameworks/base/）",
                    },
                    "query": {
                        "type": "string",
                        "description": "可选，在匹配文件中进一步搜索的关键词",
                        "default": "",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量，默认 5",
                        "default": 5,
                    },
                },
                "required": ["path"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """处理工具调用。"""
    logger.info("Tool call: %s(%s)", name, json.dumps(arguments, ensure_ascii=False))

    try:
        if name == "search_code":
            return await _handle_search_code(arguments)
        elif name == "search_symbol":
            return await _handle_search_symbol(arguments)
        elif name == "search_file":
            return await _handle_search_file(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        logger.error("Tool error: %s", e)
        return [TextContent(type="text", text=f"搜索出错: {str(e)}")]


# ─── 工具实现 ──────────────────────────────────────────

async def _handle_search_code(args: dict) -> list[TextContent]:
    query = args["query"]
    repo = args.get("repo", "") or None
    top_k = args.get("top_k", 10)

    results = await zoekt_client.search(
        query=query, top_k=top_k, score_threshold=0, repos=repo,
    )
    return [TextContent(type="text", text=_format_results(query, results))]


async def _handle_search_symbol(args: dict) -> list[TextContent]:
    symbol = args["symbol"]
    repo = args.get("repo", "") or None
    top_k = args.get("top_k", 5)

    # 使用 sym: 前缀进行符号搜索
    query = f"sym:{symbol}"
    results = await zoekt_client.search(
        query=query, top_k=top_k, score_threshold=0, repos=repo,
    )

    if not results:
        # 降级：普通搜索
        results = await zoekt_client.search(
            query=symbol, top_k=top_k, score_threshold=0, repos=repo,
        )

    return [TextContent(type="text", text=_format_results(symbol, results))]


async def _handle_search_file(args: dict) -> list[TextContent]:
    path = args["path"]
    extra_query = args.get("query", "")
    top_k = args.get("top_k", 5)

    # 使用 file: 前缀
    query = f"file:{path}"
    if extra_query:
        query = f"file:{path} {extra_query}"

    results = await zoekt_client.search(
        query=query, top_k=top_k, score_threshold=0, repos=None,
    )
    return [TextContent(type="text", text=_format_results(path, results))]


# ─── 结果格式化 ────────────────────────────────────────

def _format_results(query: str, results: list[dict]) -> str:
    """将搜索结果格式化为 LLM 友好的文本。"""
    if not results:
        return f"未找到与 \"{query}\" 相关的代码。"

    lines = [f"找到 {len(results)} 条与 \"{query}\" 相关的代码：\n"]

    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        content = r.get("content", "")
        meta = r.get("metadata", {})
        repo = meta.get("repo", "")
        path = meta.get("path", "")
        start = meta.get("start_line")
        end = meta.get("end_line")

        # 标题行
        location = f"{repo}/{path}" if repo else path or title
        if start and end:
            location += f" (L{start}-L{end})"
        lines.append(f"### {i}. {location}")

        # 代码内容
        if content and content != "(no content preview available)":
            lines.append(f"```\n{content}\n```")
        lines.append("")

    return "\n".join(lines)


# ─── 入口 ─────────────────────────────────────────────

async def main_stdio():
    """以 stdio 模式启动（供 Claude Code 等本地工具直接调用）"""
    logger.info("Starting AOSP Code Search MCP Server (stdio)")
    logger.info("Zoekt URL: %s", config.ZOEKT_URL)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


async def main_streamable_http(host: str, port: int):
    """以 Streamable HTTP 模式启动（供远程客户端通过 HTTP 访问）"""
    import uuid
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Mount
    from mcp.server.streamable_http import StreamableHTTPServerTransport

    logger.info("Starting AOSP Code Search MCP Server (streamable-http)")
    logger.info("Zoekt URL: %s", config.ZOEKT_URL)
    logger.info("Listening on http://%s:%d/mcp", host, port)

    session_id = uuid.uuid4().hex

    transport = StreamableHTTPServerTransport(
        mcp_session_id=session_id,
    )

    async def handle_mcp(scope, receive, send):
        await transport.handle_request(scope, receive, send)

    app = Starlette(
        routes=[
            Mount("/mcp", app=handle_mcp),
        ],
    )

    async with transport.connect() as (read_stream, write_stream):
        task = asyncio.create_task(
            server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
        )
        uvicorn_config = uvicorn.Config(
            app=app,
            host=host,
            port=port,
            log_level="info",
        )
        uvicorn_server = uvicorn.Server(uvicorn_config)
        await uvicorn_server.serve()
        task.cancel()


if __name__ == "__main__":
    import argparse

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
        asyncio.run(main_streamable_http(args.host, args.port))
    else:
        asyncio.run(main_stdio())
