"""
AOSP Code Search MCP — tool handlers (FastMCP)

All 7 tools registered via @mcp.tool().  HTTP calls go through the
lifespan-owned httpx.AsyncClient injected as ctx.request_context.lifespan_context.
"""

from __future__ import annotations

import logging
import uuid

import anyio
import httpx
from mcp.server.fastmcp import Context
from pydantic import BaseModel

from entry.models import (
    FileContentResult,
    ListProjectsResult,
    ListReposResult,
    ProjectInfo,
    RepoInfo,
    SearchHit,
    SearchResult,
)


class _RefinedQuerySchema(BaseModel):
    """Elicitation schema: ask user for a more specific search query."""

    refined_query: str
    scope_hint: str | None = None

logger = logging.getLogger(__name__)


# ─── Internal HTTP helpers ─────────────────────────────────────────────────────


def _client(ctx: Context) -> httpx.AsyncClient:
    return ctx.request_context.lifespan_context.http_client  # type: ignore[union-attr]


async def _post(ctx: Context, endpoint: str, body: dict, trace_id: str) -> object:
    from entry.tools_state import SOURCEPILOT_URL  # avoid circular at import time

    try:
        resp = await _client(ctx).post(
            f"{SOURCEPILOT_URL}{endpoint}",
            json=body,
            headers={"X-Trace-Id": trace_id},
        )
        resp.raise_for_status()
        resp_trace = resp.headers.get("X-Trace-Id", trace_id)
        await ctx.info(f"sourcepilot response trace_id={resp_trace}")
        return resp.json()
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        raise RuntimeError(f"SourcePilot unreachable at {SOURCEPILOT_URL}") from exc
    except httpx.HTTPStatusError as exc:
        await ctx.warning(
            f"sourcepilot non-200 status={exc.response.status_code} trace_id={trace_id}"
        )
        try:
            detail = exc.response.json().get("error", str(exc.response.status_code))
        except Exception:
            detail = str(exc.response.status_code)
        raise RuntimeError(f"SourcePilot error ({exc.response.status_code}): {detail}") from exc


async def _get(ctx: Context, endpoint: str, trace_id: str) -> object:
    from entry.tools_state import SOURCEPILOT_URL

    try:
        resp = await _client(ctx).get(
            f"{SOURCEPILOT_URL}{endpoint}",
            headers={"X-Trace-Id": trace_id},
        )
        resp.raise_for_status()
        resp_trace = resp.headers.get("X-Trace-Id", trace_id)
        await ctx.info(f"sourcepilot response trace_id={resp_trace}")
        return resp.json()
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        raise RuntimeError(f"SourcePilot unreachable at {SOURCEPILOT_URL}") from exc
    except httpx.HTTPStatusError as exc:
        await ctx.warning(
            f"sourcepilot non-200 status={exc.response.status_code} trace_id={trace_id}"
        )
        try:
            detail = exc.response.json().get("error", str(exc.response.status_code))
        except Exception:
            detail = str(exc.response.status_code)
        raise RuntimeError(f"SourcePilot error ({exc.response.status_code}): {detail}") from exc


def _build_filters(
    *,
    lang: str = "",
    branch: str = "",
    case_sensitive: str = "auto",
    project: str = "",
) -> dict:
    filters: dict = {
        "lang": lang or None,
        "branch": branch or None,
        "case_sensitive": case_sensitive,
    }
    if project:
        filters["project"] = project
    return filters


def _parse_hits(results: list[dict]) -> list[SearchHit]:
    hits = []
    for r in results:
        meta = r.get("metadata", {})
        repo = meta.get("repo", "")
        path = meta.get("path", "")
        title = r.get("title", "")
        location = f"{repo}/{path}" if repo else path or title
        hits.append(
            SearchHit(
                location=location,
                start_line=meta.get("start_line"),
                end_line=meta.get("end_line"),
                content=r.get("content", ""),
            )
        )
    return hits


def _format_hits(query: str, results: list[dict]) -> SearchResult:
    hits = _parse_hits(results)
    return SearchResult(query=query, total=len(hits), hits=hits)


# ─── Tool registration helper (called from mcp_server.py) ─────────────────────


def register_tools(mcp: object) -> None:
    """Register all 7 tools on the given FastMCP instance."""
    from mcp.server.fastmcp import FastMCP

    server: FastMCP = mcp  # type: ignore[assignment]

    @server.tool(
        description=(
            "List all available AOSP projects. In multi-project deployments, "
            "other tools must call this first to get the project name."
        )
    )
    async def list_projects(ctx: Context) -> ListProjectsResult:  # noqa: ARG001
        trace_id = str(uuid.uuid4())
        await ctx.info(f"list_projects trace_id={trace_id}")
        try:
            data = await _get(ctx, "/api/projects", trace_id)
        except RuntimeError as exc:
            logger.warning("list_projects failed: %s", exc)
            return ListProjectsResult(total=0, projects=[], multi_project=False)

        raw = data if isinstance(data, list) else data.get("projects", [])  # type: ignore[union-attr]
        projects = [
            ProjectInfo(
                name=p.get("name", ""),
            )
            for p in raw
        ]
        return ListProjectsResult(
            total=len(projects),
            projects=projects,
            multi_project=len(projects) > 1,
        )

    @server.tool(
        description=(
            "Search the AOSP codebase. Supports keywords, class names, function names, "
            "file paths, property names, etc. Returns matching code snippets and their "
            "file locations. Example: search_code(query='SystemServer startBootstrapServices')"
        )
    )
    async def search_code(
        query: str,
        project: str,
        repo: str = "",
        top_k: int = 10,
        lang: str = "",
        branch: str = "",
        case_sensitive: str = "auto",
        ctx: Context = None,  # type: ignore[assignment]
    ) -> SearchResult:
        trace_id = str(uuid.uuid4())

        # ── B7: Elicitation when query is too short ─────────────────────────
        clean_query = query.strip()
        if len(clean_query) < 3:
            elicit_result = await ctx.elicit(
                "Your query is too short to search effectively. "
                "Please provide a more specific search query.",
                _RefinedQuerySchema,
            )
            if elicit_result.action == "accept":
                clean_query = elicit_result.data.refined_query.strip()
            else:
                return SearchResult(query=query, total=0, hits=[])
        # ────────────────────────────────────────────────────────────────────

        await ctx.info(f"forwarding search_code to sourcepilot trace_id={trace_id}")
        await ctx.report_progress(progress=0, total=2, message="calling sourcepilot")

        # Cooperative cancellation check
        try:
            anyio.get_current_task()
        except Exception:
            pass

        body = {
            "query": clean_query,
            "repos": repo or None,
            "top_k": top_k,
            **_build_filters(
                lang=lang, branch=branch, case_sensitive=case_sensitive, project=project
            ),
        }
        results = await _post(ctx, "/api/search", body, trace_id)
        await ctx.report_progress(progress=2, total=2, message=f"received {len(results)} hits")  # type: ignore[arg-type]
        return _format_hits(clean_query, results)  # type: ignore[arg-type]

    @server.tool(
        description=(
            "Precise code symbol search (class names, function names, variable names). "
            "Uses Zoekt's sym: prefix for symbol search. "
            "Example: search_symbol(symbol='startBootstrapServices')"
        )
    )
    async def search_symbol(
        symbol: str,
        project: str,
        repo: str = "",
        top_k: int = 5,
        lang: str = "",
        branch: str = "",
        case_sensitive: str = "auto",
        ctx: Context = None,  # type: ignore[assignment]
    ) -> SearchResult:
        trace_id = str(uuid.uuid4())
        await ctx.info(f"forwarding search_symbol to sourcepilot trace_id={trace_id}")
        body = {
            "symbol": symbol,
            "repos": repo or None,
            "top_k": top_k,
            **_build_filters(
                lang=lang, branch=branch, case_sensitive=case_sensitive, project=project
            ),
        }
        results = await _post(ctx, "/api/search_symbol", body, trace_id)
        return _format_hits(symbol, results)  # type: ignore[arg-type]

    @server.tool(
        description=(
            "Search code files by file name or path. "
            "Uses Zoekt's file: prefix for file search. "
            "Example: search_file(path='SystemServer.java')"
        )
    )
    async def search_file(
        path: str,
        project: str,
        query: str = "",
        top_k: int = 5,
        lang: str = "",
        branch: str = "",
        case_sensitive: str = "auto",
        ctx: Context = None,  # type: ignore[assignment]
    ) -> SearchResult:
        trace_id = str(uuid.uuid4())
        await ctx.info(f"forwarding search_file to sourcepilot trace_id={trace_id}")
        body = {
            "path": path,
            "extra_query": query,
            "top_k": top_k,
            **_build_filters(
                lang=lang, branch=branch, case_sensitive=case_sensitive, project=project
            ),
        }
        results = await _post(ctx, "/api/search_file", body, trace_id)
        return _format_hits(path, results)  # type: ignore[arg-type]

    @server.tool(
        description=(
            "Search code with a regular expression. Suitable for complex pattern matching. "
            "Example: search_regex(pattern='func\\\\s+\\\\w+\\\\s*\\\\(')"
        )
    )
    async def search_regex(
        pattern: str,
        project: str,
        repo: str = "",
        top_k: int = 10,
        lang: str = "",
        branch: str = "",
        case_sensitive: str = "auto",
        ctx: Context = None,  # type: ignore[assignment]
    ) -> SearchResult:
        trace_id = str(uuid.uuid4())
        await ctx.info(f"forwarding search_regex to sourcepilot trace_id={trace_id}")

        # Cooperative cancellation: check before making the HTTP call
        cancelled_exc = anyio.get_cancelled_exc_class()
        try:
            body = {
                "pattern": pattern,
                "repos": repo or None,
                "top_k": top_k,
                **_build_filters(
                lang=lang, branch=branch, case_sensitive=case_sensitive, project=project
            ),
            }
            results = await _post(ctx, "/api/search_regex", body, trace_id)
        except cancelled_exc:
            logger.info("search_regex cancelled for pattern=%s", pattern)
            raise

        return _format_hits(f"/{pattern}/", results)  # type: ignore[arg-type]

    @server.tool(
        description=(
            "List repositories in the AOSP codebase. "
            "Can filter repository names by keyword. "
            "Example: list_repos(query='frameworks')"
        )
    )
    async def list_repos(
        project: str,
        query: str = "",
        top_k: int = 50,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> ListReposResult:
        trace_id = str(uuid.uuid4())
        await ctx.info(f"forwarding list_repos to sourcepilot trace_id={trace_id}")
        body = {
            "query": query,
            "top_k": top_k,
            "project": project or None,
        }
        repos = await _post(ctx, "/api/list_repos", body, trace_id)
        repo_list = [RepoInfo(name=r.get("name", ""), url=r.get("url", "")) for r in repos]  # type: ignore[union-attr]
        return ListReposResult(total=len(repo_list), repos=repo_list)

    @server.tool(
        description=(
            "Read the full content of an AOSP code file (or a specified line range). "
            "First use search_file to find the repo and filepath, "
            "then use this tool to read the content."
        )
    )
    async def get_file_content(
        repo: str,
        filepath: str,
        project: str,
        start_line: int = 1,
        end_line: int | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> FileContentResult:
        trace_id = str(uuid.uuid4())
        await ctx.info(f"forwarding get_file_content to sourcepilot trace_id={trace_id}")
        body = {
            "repo": repo,
            "filepath": filepath,
            "start_line": start_line,
            "end_line": end_line,
            "project": project or None,
        }
        result = await _post(ctx, "/api/get_file_content", body, trace_id)
        r = result  # type: ignore[assignment]
        return FileContentResult(
            repo=repo,
            filepath=filepath,
            start_line=r.get("start_line", start_line),  # type: ignore[union-attr]
            end_line=r.get("end_line", start_line),  # type: ignore[union-attr]
            total_lines=r.get("total_lines", 0),  # type: ignore[union-attr]
            content=r.get("content", ""),  # type: ignore[union-attr]
        )
