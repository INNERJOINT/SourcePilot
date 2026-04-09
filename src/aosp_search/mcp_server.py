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
from mcp.types import Tool, TextContent, Resource, ResourceTemplate, ReadResourceResult, TextResourceContents
from pydantic import AnyUrl

from aosp_search import config
from aosp_search import zoekt_client

# 日志配置（MCP stdio 模式下日志必须输出到 stderr）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ─── 创建 MCP Server ──────────────────────────────────

server = Server("aosp-code-search")


@server.list_resources()
async def list_resources() -> list[Resource]:
    """声明可用的资源列表。
    
    暂时返回空列表（动态资源通过 read_resource 按需获取）。
    """
    return []


@server.read_resource()
async def read_resource(uri: AnyUrl) -> ReadResourceResult:
    """通过 URI 读取资源内容。

    支持 URI 格式: aosp://{repo}/{filepath}
    示例: aosp://frameworks/base/core/java/android/os/Process.java
    
    repo 和 filepath 用第一个 '/' 之后的路径分隔：
    aosp://repo_name/path/to/file.java
    """
    uri_str = str(uri)
    if not uri_str.startswith("aosp://"):
        raise ValueError(f"不支持的 URI 格式: {uri_str}，请使用 aosp://{{repo}}/{{filepath}}")

    # 解析 repo 和 filepath
    # aosp://repo/path/to/file → repo="repo", filepath="path/to/file"
    path_part = uri_str[len("aosp://"):]
    if "/" not in path_part:
        raise ValueError(f"URI 格式错误: {uri_str}，需要包含 repo 和 filepath: aosp://{{repo}}/{{filepath}}")

    repo, filepath = path_part.split("/", 1)
    if not repo or not filepath:
        raise ValueError(f"URI 格式错误: repo 或 filepath 为空: {uri_str}")

    logger.info("read_resource: repo=%s, filepath=%s", repo, filepath)

    try:
        result = await zoekt_client.fetch_file_content(repo=repo, filepath=filepath)
    except FileNotFoundError as e:
        raise ValueError(str(e))

    content = f"# {repo}/{filepath}  (共 {result['total_lines']} 行)\n\n{result['content']}"

    return ReadResourceResult(
        contents=[
            TextResourceContents(
                uri=uri,
                mimeType="text/plain",
                text=content,
            )
        ]
    )


@server.list_resource_templates()
async def list_resource_templates() -> list[ResourceTemplate]:
    """声明支持的资源 URI 模板。
    
    客户端可通过模板构造 URI 来动态读取文件内容。
    """
    return [
        ResourceTemplate(
            name="aosp-file",
            uriTemplate="aosp://{repo}/{filepath}",
            title="AOSP 源码文件",
            description=(
                "读取 AOSP 仓库中的完整文件内容。"
                "repo: 仓库名（如 frameworks/base）；"
                "filepath: 文件路径（如 core/java/android/os/Process.java）。"
                "先用 search_file 工具获取正确的 repo 和 filepath。"
            ),
            mimeType="text/plain",
        )
    ]


@server.list_tools()
async def list_tools() -> list[Tool]:
    """声明可用的工具列表。"""
    # ─── 通用过滤参数（在多个工具中复用）─────────────
    common_filter_props = {
        "lang": {
            "type": "string",
            "description": "可选，按编程语言过滤（如 java, python, cpp, go）",
        },
        "branch": {
            "type": "string",
            "description": "可选，按分支名过滤（如 main, android-14.0.0_r1）",
        },
        "case_sensitive": {
            "type": "string",
            "enum": ["auto", "yes", "no"],
            "description": "大小写敏感模式：auto（默认，含大写则敏感）、yes、no",
            "default": "auto",
        },
    }

    return [
        Tool(
            name="search_code",
            description=(
                "搜索 AOSP 代码库。支持关键词、类名、函数名、文件路径、属性名等。"
                "返回匹配的代码片段及其文件位置。"
                "示例: search_code(query='SystemServer startBootstrapServices')"
                "示例: search_code(query='startActivity', lang='java', repo='frameworks/base')"
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
                    **common_filter_props,
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
                "示例: search_symbol(symbol='ActivityManager', lang='java')"
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
                    **common_filter_props,
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
                "示例: search_file(path='Android.bp', lang='starlark')"
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
                    **common_filter_props,
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="search_regex",
            description=(
                "使用正则表达式搜索代码。适合复杂模式匹配。"
                "示例: search_regex(pattern='func\\s+\\w+\\s*\\(')"
                "示例: search_regex(pattern='TODO.*fix', lang='java')"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "正则表达式模式",
                    },
                    "repo": {
                        "type": "string",
                        "description": "可选，限定搜索的 repo",
                        "default": "",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量，默认 10",
                        "default": 10,
                    },
                    "lang": common_filter_props["lang"],
                },
                "required": ["pattern"],
            },
        ),
        Tool(
            name="list_repos",
            description=(
                "列出 AOSP 代码库中的仓库列表。"
                "可按关键词过滤仓库名称。"
                "示例: list_repos(query='frameworks')"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "可选，仓库名过滤关键词",
                        "default": "",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回数量上限，默认 50",
                        "default": 50,
                    },
                },
            },
        ),
        Tool(
            name="get_file_content",
            description=(
                "读取 AOSP 代码文件的完整内容（或指定行范围）。"
                "先用 search_file 找到文件的 repo 和 filepath，再用此工具读取完整内容。"
                "示例: get_file_content(repo='layoutlib', filepath='bridge/src/android/app/Foo.java')"
                "示例（读取指定行）: get_file_content(repo='frameworks/base', filepath='core/java/android/os/Process.java', start_line=100, end_line=200)"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "仓库名（从 search_file/search_code 结果的 repo 字段获取）",
                    },
                    "filepath": {
                        "type": "string",
                        "description": "文件路径（从搜索结果的 path 字段获取，不含 repo 前缀）",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "起始行号（从 1 开始，默认 1，即文件开头）",
                        "default": 1,
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "结束行号（默认读取到文件末尾）",
                    },
                },
                "required": ["repo", "filepath"],
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
        elif name == "search_regex":
            return await _handle_search_regex(arguments)
        elif name == "list_repos":
            return await _handle_list_repos(arguments)
        elif name == "get_file_content":
            return await _handle_get_file_content(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        logger.error("Tool error: %s", e)
        return [TextContent(type="text", text=f"操作出错: {str(e)}")]


# ─── 工具实现 ──────────────────────────────────────────

def _extract_filters(args: dict) -> dict:
    """从工具参数中提取通用过滤字段。"""
    return {
        "lang": args.get("lang") or None,
        "branch": args.get("branch") or None,
        "case_sensitive": args.get("case_sensitive", "auto"),
    }


async def _handle_search_code(args: dict) -> list[TextContent]:
    query = args["query"]
    repo = args.get("repo", "") or None
    top_k = args.get("top_k", 10)
    filters = _extract_filters(args)

    # NL 增强判断
    if config.NL_ENABLED:
        from nl.classifier import classify_query
        query_type = classify_query(query)
    else:
        query_type = "exact"

    logger.info("Query type: %s (NL_ENABLED=%s)", query_type, config.NL_ENABLED)

    if query_type == "natural_language":
        from aosp_search.nl_search import nl_search
        results = await nl_search(
            query=query, top_k=top_k, score_threshold=0,
            repos=repo, lang=filters.get("lang"), branch=filters.get("branch"),
        )
    else:
        results = await zoekt_client.search(
            query=query, top_k=top_k, score_threshold=0, repos=repo, **filters,
        )
    return [TextContent(type="text", text=_format_results(query, results))]


async def _handle_search_symbol(args: dict) -> list[TextContent]:
    symbol = args["symbol"]
    repo = args.get("repo", "") or None
    top_k = args.get("top_k", 5)
    filters = _extract_filters(args)

    # 使用 sym: 前缀进行符号搜索
    query = f"sym:{symbol}"
    results = await zoekt_client.search(
        query=query, top_k=top_k, score_threshold=0, repos=repo, **filters,
    )

    if not results:
        # 降级：普通搜索
        results = await zoekt_client.search(
            query=symbol, top_k=top_k, score_threshold=0, repos=repo, **filters,
        )

    return [TextContent(type="text", text=_format_results(symbol, results))]


async def _handle_search_file(args: dict) -> list[TextContent]:
    path = args["path"]
    extra_query = args.get("query", "")
    top_k = args.get("top_k", 5)
    filters = _extract_filters(args)

    # 使用 file: 前缀
    query = f"file:{path}"
    if extra_query:
        query = f"file:{path} {extra_query}"

    results = await zoekt_client.search(
        query=query, top_k=top_k, score_threshold=0, repos=None, **filters,
    )
    return [TextContent(type="text", text=_format_results(path, results))]


async def _handle_search_regex(args: dict) -> list[TextContent]:
    pattern = args["pattern"]
    repo = args.get("repo", "") or None
    top_k = args.get("top_k", 10)
    lang = args.get("lang") or None

    results = await zoekt_client.search_regex(
        pattern=pattern, top_k=top_k, score_threshold=0,
        repos=repo, lang=lang,
    )
    return [TextContent(type="text", text=_format_results(f"/{pattern}/", results))]


async def _handle_list_repos(args: dict) -> list[TextContent]:
    query = args.get("query", "")
    top_k = args.get("top_k", 50)

    repos = await zoekt_client.list_repos(query=query, top_k=top_k)

    if not repos:
        return [TextContent(type="text", text="未找到匹配的仓库。")]

    lines = [f"找到 {len(repos)} 个仓库：\n"]
    for i, r in enumerate(repos, 1):
        name = r.get("name", "")
        url = r.get("url", "")
        line = f"{i}. {name}"
        if url:
            line += f"  ({url})"
        lines.append(line)

    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_get_file_content(args: dict) -> list[TextContent]:
    repo = args["repo"]
    filepath = args["filepath"]
    start_line = args.get("start_line", 1)
    end_line = args.get("end_line", None)

    result = await zoekt_client.fetch_file_content(
        repo=repo,
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
    )

    total = result["total_lines"]
    s = result["start_line"]
    e = result["end_line"]
    header = f"# {repo}/{filepath}  (L{s}-L{e} / 共 {total} 行)\n"

    return [TextContent(type="text", text=header + "```\n" + result["content"] + "\n```")]


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
    import contextlib
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route
    from starlette.responses import JSONResponse
    from starlette.types import ASGIApp, Receive, Scope, Send
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    logger.info("Starting AOSP Code Search MCP Server (streamable-http)")
    logger.info("Zoekt URL: %s", config.ZOEKT_URL)
    logger.info("Listening on http://%s:%d/mcp", host, port)

    auth_token = config.MCP_AUTH_TOKEN
    if auth_token:
        logger.info("Bearer token authentication ENABLED")
    else:
        logger.warning("Bearer token authentication DISABLED (set MCP_AUTH_TOKEN to enable)")

    # ─── Session 管理器（每个客户端连接独立的 session）──
    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=False,
        stateless=False,          # 有状态模式，保持 session
    )

    async def handle_mcp(scope, receive, send):
        await session_manager.handle_request(scope, receive, send)

    # ─── Bearer Token 鉴权中间件 ───────────────────────
    class BearerTokenMiddleware:
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

    # ─── lifespan：管理 session_manager 的生命周期 ─────
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

    # 如果设置了 token，包裹鉴权中间件
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
