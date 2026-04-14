"""
AOSP Code Search MCP Server — shared handlers

Contains the MCP Server object, all @server decorated handlers,
tool implementation functions, and result formatting.
All business logic delegates to SourcePilot HTTP API.
"""

import json
import logging
import os
import sys
import uuid

import httpx
from mcp.server import Server
from mcp.types import Tool, TextContent, Resource, ResourceTemplate, ReadResourceResult, TextResourceContents
from pydantic import AnyUrl

# 日志配置（MCP stdio 模式下日志必须输出到 stderr）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

SOURCEPILOT_URL = os.getenv("SOURCEPILOT_URL", "http://localhost:9000")

# module-level httpx.AsyncClient singleton
_http_client = httpx.AsyncClient(timeout=30.0)

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
    """
    uri_str = str(uri)
    if not uri_str.startswith("aosp://"):
        raise ValueError(f"不支持的 URI 格式: {uri_str}，请使用 aosp://{{repo}}/{{filepath}}")

    path_part = uri_str[len("aosp://"):]
    if "/" not in path_part:
        raise ValueError(f"URI 格式错误: {uri_str}，需要包含 repo 和 filepath: aosp://{{repo}}/{{filepath}}")

    repo, filepath = path_part.split("/", 1)
    if not repo or not filepath:
        raise ValueError(f"URI 格式错误: repo 或 filepath 为空: {uri_str}")

    logger.info("read_resource: repo=%s, filepath=%s", repo, filepath)

    trace_id = str(uuid.uuid4())
    try:
        resp = await _http_client.post(
            f"{SOURCEPILOT_URL}/api/get_file_content",
            json={"repo": repo, "filepath": filepath},
            headers={"X-Trace-Id": trace_id},
        )
        resp.raise_for_status()
        result = resp.json()
    except httpx.TimeoutException:
        raise ValueError(f"SourcePilot unreachable at {SOURCEPILOT_URL}")
    except httpx.ConnectError:
        raise ValueError(f"SourcePilot unreachable at {SOURCEPILOT_URL}")
    except httpx.HTTPStatusError as e:
        raise ValueError(f"SourcePilot error: {e.response.status_code}")

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
    """声明支持的资源 URI 模板。"""
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

    trace_id = str(uuid.uuid4())
    try:
        if name == "search_code":
            result = await _handle_search_code(arguments, trace_id)
        elif name == "search_symbol":
            result = await _handle_search_symbol(arguments, trace_id)
        elif name == "search_file":
            result = await _handle_search_file(arguments, trace_id)
        elif name == "search_regex":
            result = await _handle_search_regex(arguments, trace_id)
        elif name == "list_repos":
            result = await _handle_list_repos(arguments, trace_id)
        elif name == "get_file_content":
            result = await _handle_get_file_content(arguments, trace_id)
        else:
            result = [TextContent(type="text", text=f"Unknown tool: {name}")]

        return result
    except Exception as e:
        logger.error("Tool error: %s", e)
        return [TextContent(type="text", text=f"操作出错: {str(e)}")]


# ─── 工具实现 ──────────────────────────────────────────

async def _post(endpoint: str, body: dict, trace_id: str) -> dict:
    """向 SourcePilot 发送 POST 请求，统一处理连接错误。"""
    try:
        resp = await _http_client.post(
            f"{SOURCEPILOT_URL}{endpoint}",
            json=body,
            headers={"X-Trace-Id": trace_id},
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.TimeoutException, httpx.ConnectError):
        raise RuntimeError(f"SourcePilot unreachable at {SOURCEPILOT_URL}")
    except httpx.HTTPStatusError as e:
        # Try to extract error message from SourcePilot JSON response
        try:
            detail = e.response.json().get("error", str(e.response.status_code))
        except Exception:
            detail = str(e.response.status_code)
        raise RuntimeError(f"SourcePilot error ({e.response.status_code}): {detail}")


def _extract_filters(args: dict) -> dict:
    """从工具参数中提取通用过滤字段。"""
    return {
        "lang": args.get("lang") or None,
        "branch": args.get("branch") or None,
        "case_sensitive": args.get("case_sensitive", "auto"),
    }


async def _handle_search_code(args: dict, trace_id: str) -> list[TextContent]:
    query = args["query"]
    body = {
        "query": query,
        "repos": args.get("repo", "") or None,
        "top_k": args.get("top_k", 10),
        **_extract_filters(args),
    }
    results = await _post("/api/search", body, trace_id)
    return [TextContent(type="text", text=_format_results(query, results))]


async def _handle_search_symbol(args: dict, trace_id: str) -> list[TextContent]:
    symbol = args["symbol"]
    body = {
        "symbol": symbol,
        "repos": args.get("repo", "") or None,
        "top_k": args.get("top_k", 5),
        **_extract_filters(args),
    }
    results = await _post("/api/search_symbol", body, trace_id)
    return [TextContent(type="text", text=_format_results(symbol, results))]


async def _handle_search_file(args: dict, trace_id: str) -> list[TextContent]:
    path = args["path"]
    body = {
        "path": path,
        "extra_query": args.get("query", ""),
        "top_k": args.get("top_k", 5),
        **_extract_filters(args),
    }
    results = await _post("/api/search_file", body, trace_id)
    return [TextContent(type="text", text=_format_results(path, results))]


async def _handle_search_regex(args: dict, trace_id: str) -> list[TextContent]:
    pattern = args["pattern"]
    body = {
        "pattern": pattern,
        "repos": args.get("repo", "") or None,
        "top_k": args.get("top_k", 10),
        "lang": args.get("lang") or None,
    }
    results = await _post("/api/search_regex", body, trace_id)
    return [TextContent(type="text", text=_format_results(f"/{pattern}/", results))]


async def _handle_list_repos(args: dict, trace_id: str) -> list[TextContent]:
    body = {
        "query": args.get("query", ""),
        "top_k": args.get("top_k", 50),
    }
    repos = await _post("/api/list_repos", body, trace_id)

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


async def _handle_get_file_content(args: dict, trace_id: str) -> list[TextContent]:
    repo = args["repo"]
    filepath = args["filepath"]
    body = {
        "repo": repo,
        "filepath": filepath,
        "start_line": args.get("start_line", 1),
        "end_line": args.get("end_line"),
    }
    result = await _post("/api/get_file_content", body, trace_id)

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

        location = f"{repo}/{path}" if repo else path or title
        if start and end:
            location += f" (L{start}-L{end})"
        lines.append(f"### {i}. {location}")

        if content and content != "(no content preview available)":
            lines.append(f"```\n{content}\n```")
        lines.append("")

    return "\n".join(lines)
