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
from contextvars import ContextVar

import httpx
from mcp.server import Server
from mcp.types import (
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    TextContent,
    TextResourceContents,
    Tool,
)
from pydantic import AnyUrl

# Logging config (in MCP stdio mode logs MUST go to stderr)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

SOURCEPILOT_URL = os.getenv("SOURCEPILOT_URL", "http://localhost:9000")

# ContextVar-based HTTP client (set by lifespan in mcp_http.py and mcp_stdio.py)
_http_client_ctx: ContextVar[httpx.AsyncClient] = ContextVar("_http_client_ctx")


def _set_http_client(client: httpx.AsyncClient) -> None:
    _http_client_ctx.set(client)


def _get_http_client() -> httpx.AsyncClient:
    return _http_client_ctx.get()

# ─── Multi-project probe state ─────────────────────────
_multi_project: bool | None = None
_project_names: list[str] = []

# ─── Common property definitions ───────────────────────
_PROJECT_PROP = {
    "type": "string",
    "description": "Optional, project name (e.g. aosp-14, aosp-15). If unspecified, the default project is used.",
}

# ─── Create MCP Server ────────────────────────────────

server = Server("aosp-code-search")


async def _probe_projects() -> None:
    """Probe SourcePilot /api/projects and update multi-project state. Degrades on failure, never raises."""
    global _multi_project, _project_names
    for attempt in range(2):
        try:
            resp = await _get_http_client().get(
                f"{SOURCEPILOT_URL}/api/projects",
                headers={"X-Trace-Id": str(uuid.uuid4())},
                timeout=2.0,
            )
            resp.raise_for_status()
            data = resp.json()
            # data is expected to be list[dict] or dict with "projects" key
            if isinstance(data, list):
                projects = data
            else:
                projects = data.get("projects", [])
            _project_names = [p.get("name", "") for p in projects if p.get("name")]
            _multi_project = len(_project_names) > 1
            logger.info(
                "_probe_projects: found %d projects, multi=%s", len(_project_names), _multi_project
            )
            return
        except Exception as exc:
            if attempt == 0:
                logger.warning("_probe_projects attempt 1 failed: %s, retrying…", exc)
            else:
                logger.warning("_probe_projects failed after 2 attempts: %s", exc)
    # Keep _multi_project = None (probe inconclusive)


@server.list_resources()
async def list_resources() -> list[Resource]:
    """Declare the list of available resources.

    Returns an empty list for now (dynamic resources are fetched on demand via read_resource).
    """
    return []


@server.read_resource()
async def read_resource(uri: AnyUrl) -> ReadResourceResult:
    """Read resource content via URI.

    Supported URI format: aosp://{repo}/{filepath}
    Example: aosp://frameworks/base/core/java/android/os/Process.java
    """
    uri_str = str(uri)
    if not uri_str.startswith("aosp://"):
        raise ValueError(f"Unsupported URI format: {uri_str}, please use aosp://{{repo}}/{{filepath}}")

    path_part = uri_str[len("aosp://"):]
    if "/" not in path_part:
        raise ValueError(f"Invalid URI format: {uri_str}, must contain repo and filepath: aosp://{{repo}}/{{filepath}}")

    repo, filepath = path_part.split("/", 1)
    if not repo or not filepath:
        raise ValueError(f"Invalid URI format: repo or filepath is empty: {uri_str}")

    logger.info("read_resource: repo=%s, filepath=%s", repo, filepath)

    trace_id = str(uuid.uuid4())
    try:
        resp = await _get_http_client().post(
            f"{SOURCEPILOT_URL}/api/get_file_content",
            json={"repo": repo, "filepath": filepath},
            headers={"X-Trace-Id": trace_id},
        )
        resp.raise_for_status()
        result = resp.json()
    except httpx.TimeoutException as exc:
        raise ValueError(f"SourcePilot unreachable at {SOURCEPILOT_URL}") from exc
    except httpx.ConnectError as exc:
        raise ValueError(f"SourcePilot unreachable at {SOURCEPILOT_URL}") from exc
    except httpx.HTTPStatusError as e:
        raise ValueError(f"SourcePilot error: {e.response.status_code}") from e

    total_lines = result.get("total_lines", 0)
    file_content = result.get("content", "")
    content = f"# {repo}/{filepath}  ({total_lines} lines total)\n\n{file_content}"

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
    """Declare the supported resource URI templates."""
    return [
        ResourceTemplate(
            name="aosp-file",
            uriTemplate="aosp://{repo}/{filepath}",
            title="AOSP source file",
            description=(
                "Read the full content of a file in an AOSP repository. "
                "repo: repository name (e.g. frameworks/base); "
                "filepath: file path (e.g. core/java/android/os/Process.java). "
                "First use the search_file tool to obtain the correct repo and filepath."
            ),
            mimeType="text/plain",
        )
    ]


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Declare the list of available tools."""
    global _multi_project
    if _multi_project is None:
        await _probe_projects()
    if _multi_project is None:
        logger.warning("list_tools: project probe incomplete, using optional project behavior")

    # Build the project property description (multi-project: include allowed values)
    if _multi_project and _project_names:
        names_str = ", ".join(_project_names)
        project_prop_required = {
            "type": "string",
            "description": f"Required, allowed values: {names_str}",
        }
        project_prop_optional = {
            "type": "string",
            "description": f"Optional, project name. Allowed values: {names_str}",
        }
    elif not _multi_project and _project_names:
        default_name = _project_names[0]
        project_prop_required = _PROJECT_PROP
        project_prop_optional = {
            "type": "string",
            "description": f"Optional, project name (e.g. aosp-14, aosp-15). Default: {default_name}",
        }
    else:
        project_prop_required = _PROJECT_PROP
        project_prop_optional = _PROJECT_PROP

    # In multi-project mode, search-style tools require the project field
    search_required_base = ["query"]
    symbol_required_base = ["symbol"]
    file_required_base = ["path"]
    regex_required_base = ["pattern"]
    list_repos_required_base: list[str] = []
    get_file_required_base = ["repo", "filepath"]

    if _multi_project:
        search_required = search_required_base + ["project"]
        symbol_required = symbol_required_base + ["project"]
        file_required = file_required_base + ["project"]
        regex_required = regex_required_base + ["project"]
        list_repos_required = list_repos_required_base + ["project"]
        get_file_required = get_file_required_base + ["project"]
        project_prop = project_prop_required
    else:
        search_required = search_required_base
        symbol_required = symbol_required_base
        file_required = file_required_base
        regex_required = regex_required_base
        list_repos_required = list_repos_required_base
        get_file_required = get_file_required_base
        project_prop = project_prop_optional

    common_filter_props = {
        "lang": {
            "type": "string",
            "description": "Optional, filter by programming language (e.g. java, python, cpp, go)",
        },
        "branch": {
            "type": "string",
            "description": "Optional, filter by branch name (e.g. main, android-14.0.0_r1)",
        },
        "case_sensitive": {
            "type": "string",
            "enum": ["auto", "yes", "no"],
            "description": "Case sensitivity mode: auto (default, sensitive when query contains uppercase), yes, no",
            "default": "auto",
        },
        "project": project_prop,
    }

    return [
        Tool(
            name="list_projects",
            description=(
                "List all available AOSP projects. "
                "In multi-project deployments, other tools must call this first to get the project name."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="search_code",
            description=(
                "Search the AOSP codebase. Supports keywords, class names, function names, "
                "file paths, property names, etc. Returns matching code snippets and their file locations. "
                "Example: search_code(query='SystemServer startBootstrapServices') "
                "Example: search_code(query='startActivity', lang='java', repo='frameworks/base')"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query: keyword, symbol name, file path, property name, etc.",
                    },
                    "repo": {
                        "type": "string",
                        "description": "Optional, restrict search to repo name prefix (e.g. frameworks/base)",
                        "default": "",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return, default 10",
                        "default": 10,
                    },
                    **common_filter_props,
                },
                "required": search_required,
            },
        ),
        Tool(
            name="search_symbol",
            description=(
                "Precise code symbol search (class names, function names, variable names). "
                "Uses Zoekt's sym: prefix for symbol search. "
                "Example: search_symbol(symbol='startBootstrapServices') "
                "Example: search_symbol(symbol='ActivityManager', lang='java')"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Symbol name to search for (class name, function name, etc.)",
                    },
                    "repo": {
                        "type": "string",
                        "description": "Optional, restrict search to repo",
                        "default": "",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return, default 5",
                        "default": 5,
                    },
                    **common_filter_props,
                },
                "required": symbol_required,
            },
        ),
        Tool(
            name="search_file",
            description=(
                "Search code files by file name or path. "
                "Uses Zoekt's file: prefix for file search. "
                "Example: search_file(path='SystemServer.java') "
                "Example: search_file(path='Android.bp', lang='starlark')"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "File name or path pattern (e.g. SystemServer.java or frameworks/base/)"
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional, additional keyword to search within matched files",
                        "default": "",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return, default 5",
                        "default": 5,
                    },
                    **common_filter_props,
                },
                "required": file_required,
            },
        ),
        Tool(
            name="search_regex",
            description=(
                "Search code with a regular expression. Suitable for complex pattern matching. "
                "Example: search_regex(pattern='func\\s+\\w+\\s*\\(') "
                "Example: search_regex(pattern='TODO.*fix', lang='java')"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regular expression pattern",
                    },
                    "repo": {
                        "type": "string",
                        "description": "Optional, restrict search to repo",
                        "default": "",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return, default 10",
                        "default": 10,
                    },
                    "lang": common_filter_props["lang"],
                    "branch": common_filter_props["branch"],
                    "case_sensitive": common_filter_props["case_sensitive"],
                    "project": project_prop,
                },
                "required": regex_required,
            },
        ),
        Tool(
            name="list_repos",
            description=(
                "List repositories in the AOSP codebase. "
                "Can filter repository names by keyword. "
                "Example: list_repos(query='frameworks')"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional, repo name filter keyword",
                        "default": "",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of results to return, default 50",
                        "default": 50,
                    },
                    "project": project_prop,
                },
                "required": list_repos_required,
            },
        ),
        Tool(
            name="get_file_content",
            description=(
                "Read the full content of an AOSP code file (or a specified line range). "
                "First use search_file to find the file's repo and filepath, then use this tool to read content. "
                "Example: get_file_content(repo='layoutlib',"
                " filepath='bridge/src/android/app/Foo.java') "
                "Example (specific line range): get_file_content(repo='frameworks/base',"
                " filepath='core/java/android/os/Process.java',"
                " start_line=100, end_line=200)"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repo name (from the repo field of search_file/search_code results)",
                    },
                    "filepath": {
                        "type": "string",
                        "description": "File path (from the path field of search results, without repo prefix)",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Start line number (1-based, default 1, i.e. start of file)",
                        "default": 1,
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "End line number (defaults to end of file)",
                    },
                    "project": project_prop,
                },
                "required": get_file_required,
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    global _multi_project
    if _multi_project is None:
        await _probe_projects()

    logger.info("Tool call: %s(%s)", name, json.dumps(arguments, ensure_ascii=False))

    trace_id = str(uuid.uuid4())
    try:
        if name == "list_projects":
            result = await _handle_list_projects(arguments, trace_id)
        elif name == "search_code":
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
        return [TextContent(type="text", text=f"Tool error: {str(e)}")]


# ─── Tool implementations ─────────────────────────────

async def _post(endpoint: str, body: dict, trace_id: str) -> dict:
    """Send a POST request to SourcePilot, with unified connection error handling."""
    try:
        resp = await _get_http_client().post(
            f"{SOURCEPILOT_URL}{endpoint}",
            json=body,
            headers={"X-Trace-Id": trace_id},
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        raise RuntimeError(f"SourcePilot unreachable at {SOURCEPILOT_URL}") from exc
    except httpx.HTTPStatusError as e:
        # Try to extract error message from SourcePilot JSON response
        try:
            detail = e.response.json().get("error", str(e.response.status_code))
        except Exception:
            detail = str(e.response.status_code)
        raise RuntimeError(f"SourcePilot error ({e.response.status_code}): {detail}") from e


async def _get(endpoint: str, trace_id: str) -> dict | list:
    """Send a GET request to SourcePilot, with unified connection error handling."""
    try:
        resp = await _get_http_client().get(
            f"{SOURCEPILOT_URL}{endpoint}",
            headers={"X-Trace-Id": trace_id},
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        raise RuntimeError(f"SourcePilot unreachable at {SOURCEPILOT_URL}") from exc
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json().get("error", str(e.response.status_code))
        except Exception:
            detail = str(e.response.status_code)
        raise RuntimeError(f"SourcePilot error ({e.response.status_code}): {detail}") from e


def _extract_filters(args: dict) -> dict:
    """Extract common filter fields from tool arguments."""
    result = {
        "lang": args.get("lang") or None,
        "branch": args.get("branch") or None,
        "case_sensitive": args.get("case_sensitive", "auto"),
    }
    project = args.get("project") or None
    if project:
        result["project"] = project
    return result


async def _handle_list_projects(args: dict, trace_id: str) -> list[TextContent]:  # noqa: ARG001
    try:
        data = await _get("/api/projects", trace_id)
    except RuntimeError as e:
        return [TextContent(type="text", text=f"Failed to fetch project list: {e}")]

    if isinstance(data, list):
        projects = data
    else:
        projects = data.get("projects", [])

    if not projects:
        return [TextContent(type="text", text="No projects found.")]

    lines = [f"Found {len(projects)} available projects:\n"]
    lines.append(f"{'name'}")
    lines.append("-" * 40)
    for p in projects:
        name = p.get("name", "")
        lines.append(f"{name}")

    if len(projects) > 1:
        lines.append("\nNote: in multi-project deployments, other tools must pass the 'project' field to specify the target project.")

    return [TextContent(type="text", text="\n".join(lines))]


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
        **_extract_filters(args),
    }
    results = await _post("/api/search_regex", body, trace_id)
    return [TextContent(type="text", text=_format_results(f"/{pattern}/", results))]


async def _handle_list_repos(args: dict, trace_id: str) -> list[TextContent]:
    body = {
        "query": args.get("query", ""),
        "top_k": args.get("top_k", 50),
        "project": args.get("project") or None,
    }
    repos = await _post("/api/list_repos", body, trace_id)

    if not repos:
        return [TextContent(type="text", text="No matching repositories found.")]

    lines = [f"Found {len(repos)} repositories:\n"]
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
        "project": args.get("project") or None,
    }
    result = await _post("/api/get_file_content", body, trace_id)

    total = result.get("total_lines")
    s = result.get("start_line")
    e = result.get("end_line")
    content = result.get("content")
    if total is None or s is None or e is None or content is None:
        return [TextContent(type="text", text="SourcePilot returned malformed response (status N/A)")]  # noqa: E501
    header = f"# {repo}/{filepath}  (L{s}-L{e} / {total} lines total)\n"

    return [TextContent(type="text", text=header + "```\n" + content + "\n```")]


# ─── Result formatting ────────────────────────────────

def _format_results(query: str, results: list[dict]) -> str:
    """Format search results into LLM-friendly text."""
    if not results:
        return f"No code found matching \"{query}\"."

    lines = [f"Found {len(results)} code results matching \"{query}\":\n"]

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
