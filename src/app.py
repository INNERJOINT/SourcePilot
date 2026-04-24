"""
SourcePilot HTTP API

Exposes gateway functions as REST endpoints over Starlette/uvicorn.
"""

import asyncio
import contextlib
import json
import logging
import sys

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from gateway import gateway
from observability.audit import (
    audit_tool_call,
    audit_stats,
    new_trace_id,
    setup_audit_logger,
    start_audit_listener,
    stop_audit_listener,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


# ─── Response helpers ─────────────────────────────────

def _ok(data) -> JSONResponse:
    return JSONResponse(data)


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


async def _parse_json(request: Request) -> tuple[dict | None, JSONResponse | None]:
    try:
        body = await request.json()
        return body, None
    except Exception:
        return None, _err(400, "请求体必须是合法的 JSON")


def _trace_from_request(request: Request) -> str:
    """读取或生成本次请求的 trace_id。"""
    tid = request.headers.get("X-Trace-Id")
    if tid:
        from observability.audit import _trace_id
        _trace_id.set(tid)
        return tid
    return new_trace_id()


# ─── Endpoints ────────────────────────────────────────

async def health(request: Request) -> JSONResponse:
    import config
    from config import list_projects, get_project
    from adapters.zoekt import ZoektAdapter

    # Check each project's Zoekt instance
    projects_status = {}
    for proj in list_projects():
        name = proj["name"]
        try:
            adapter = ZoektAdapter(zoekt_url=proj["zoekt_url"])
            ok = await adapter.health_check()
            projects_status[name] = ok
        except Exception:
            projects_status[name] = False

    backends: dict = {"zoekt": projects_status}
    if config.DENSE_ENABLED:
        backends["dense"] = True
    if config.GRAPH_ENABLED:
        try:
            from adapters.graph import GraphAdapter
            adapter = GraphAdapter()
            backends["graph"] = await adapter.health_check()
        except Exception:
            backends["graph"] = False
    return _ok({"status": "ok", "service": "sourcepilot", "backends": backends})


async def api_search(request: Request) -> JSONResponse:
    body, err = await _parse_json(request)
    if err:
        return err

    query = body.get("query")
    if not query:
        return _err(400, "缺少必填参数 query")

    top_k = body.get("top_k", 10)
    score_threshold = body.get("score_threshold", 0.0)
    repos = body.get("repos") or None
    lang = body.get("lang") or None
    branch = body.get("branch") or None
    case_sensitive = body.get("case_sensitive", "auto")
    project = body.get("project") or None

    _trace_from_request(request)
    args = {
        "query": query,
        "top_k": top_k,
        "score_threshold": score_threshold,
        "repos": repos,
        "lang": lang,
        "branch": branch,
        "case_sensitive": case_sensitive,
        "project": project,
    }

    async with audit_tool_call("search", args, "http") as ctx:
        try:
            results = await gateway.search(
                query=query,
                top_k=top_k,
                score_threshold=score_threshold,
                repos=repos,
                lang=lang,
                branch=branch,
                case_sensitive=case_sensitive,
                project=project,
            )
            ctx.set_result_count(len(results))
            return _ok(results)
        except httpx.RequestError as e:
            ctx.set_error(str(e))
            return _err(502, f"Zoekt 不可达: {e}")
        except Exception as e:
            ctx.set_error(str(e))
            logger.error("api_search error: %s", e)
            return _err(500, str(e))


async def api_search_symbol(request: Request) -> JSONResponse:
    body, err = await _parse_json(request)
    if err:
        return err

    symbol = body.get("symbol")
    if not symbol:
        return _err(400, "缺少必填参数 symbol")

    top_k = body.get("top_k", 5)
    repos = body.get("repos") or None
    lang = body.get("lang") or None
    branch = body.get("branch") or None
    case_sensitive = body.get("case_sensitive", "auto")
    project = body.get("project") or None

    _trace_from_request(request)
    args = {
        "symbol": symbol,
        "top_k": top_k,
        "repos": repos,
        "lang": lang,
        "branch": branch,
        "case_sensitive": case_sensitive,
        "project": project,
    }

    async with audit_tool_call("search_symbol", args, "http") as ctx:
        try:
            results = await gateway.search_symbol(
                symbol=symbol,
                top_k=top_k,
                repos=repos,
                lang=lang,
                branch=branch,
                case_sensitive=case_sensitive,
                project=project,
            )
            ctx.set_result_count(len(results))
            return _ok(results)
        except httpx.RequestError as e:
            ctx.set_error(str(e))
            return _err(502, f"Zoekt 不可达: {e}")
        except Exception as e:
            ctx.set_error(str(e))
            logger.error("api_search_symbol error: %s", e)
            return _err(500, str(e))


async def api_search_file(request: Request) -> JSONResponse:
    body, err = await _parse_json(request)
    if err:
        return err

    path = body.get("path")
    if not path:
        return _err(400, "缺少必填参数 path")

    extra_query = body.get("extra_query", "")
    top_k = body.get("top_k", 5)
    lang = body.get("lang") or None
    branch = body.get("branch") or None
    case_sensitive = body.get("case_sensitive", "auto")
    project = body.get("project") or None

    _trace_from_request(request)
    args = {
        "path": path,
        "extra_query": extra_query,
        "top_k": top_k,
        "lang": lang,
        "branch": branch,
        "case_sensitive": case_sensitive,
        "project": project,
    }

    async with audit_tool_call("search_file", args, "http") as ctx:
        try:
            results = await gateway.search_file(
                path=path,
                extra_query=extra_query,
                top_k=top_k,
                lang=lang,
                branch=branch,
                case_sensitive=case_sensitive,
                project=project,
            )
            ctx.set_result_count(len(results))
            return _ok(results)
        except httpx.RequestError as e:
            ctx.set_error(str(e))
            return _err(502, f"Zoekt 不可达: {e}")
        except Exception as e:
            ctx.set_error(str(e))
            logger.error("api_search_file error: %s", e)
            return _err(500, str(e))


async def api_search_regex(request: Request) -> JSONResponse:
    body, err = await _parse_json(request)
    if err:
        return err

    pattern = body.get("pattern")
    if not pattern:
        return _err(400, "缺少必填参数 pattern")

    top_k = body.get("top_k", 10)
    repos = body.get("repos") or None
    lang = body.get("lang") or None
    project = body.get("project") or None

    _trace_from_request(request)
    args = {
        "pattern": pattern,
        "top_k": top_k,
        "repos": repos,
        "lang": lang,
        "project": project,
    }

    async with audit_tool_call("search_regex", args, "http") as ctx:
        try:
            results = await gateway.search_regex(
                pattern=pattern,
                top_k=top_k,
                repos=repos,
                lang=lang,
                project=project,
            )
            ctx.set_result_count(len(results))
            return _ok(results)
        except httpx.RequestError as e:
            ctx.set_error(str(e))
            return _err(502, f"Zoekt 不可达: {e}")
        except Exception as e:
            ctx.set_error(str(e))
            logger.error("api_search_regex error: %s", e)
            return _err(500, str(e))


async def api_list_repos(request: Request) -> JSONResponse:
    body, err = await _parse_json(request)
    if err:
        return err

    query = body.get("query", "")
    top_k = body.get("top_k", 50)
    project = body.get("project") or None

    _trace_from_request(request)
    args = {"query": query, "top_k": top_k, "project": project}

    async with audit_tool_call("list_repos", args, "http") as ctx:
        try:
            results = await gateway.list_repos(query=query, top_k=top_k, project=project)
            ctx.set_result_count(len(results))
            return _ok(results)
        except httpx.RequestError as e:
            ctx.set_error(str(e))
            return _err(502, f"Zoekt 不可达: {e}")
        except Exception as e:
            ctx.set_error(str(e))
            logger.error("api_list_repos error: %s", e)
            return _err(500, str(e))


async def api_get_file_content(request: Request) -> JSONResponse:
    body, err = await _parse_json(request)
    if err:
        return err

    repo = body.get("repo")
    filepath = body.get("filepath")
    if not repo or not filepath:
        return _err(400, "缺少必填参数 repo 或 filepath")

    start_line = body.get("start_line", 1)
    end_line = body.get("end_line") or None
    project = body.get("project") or None

    _trace_from_request(request)
    args = {
        "repo": repo,
        "filepath": filepath,
        "start_line": start_line,
        "end_line": end_line,
        "project": project,
    }

    async with audit_tool_call("get_file_content", args, "http") as ctx:
        try:
            result = await gateway.get_file_content(
                repo=repo,
                filepath=filepath,
                start_line=start_line,
                end_line=end_line,
                project=project,
            )
            ctx.set_result_count(1)
            return _ok(result)
        except FileNotFoundError as e:
            ctx.set_error(str(e))
            return _err(404, str(e))
        except httpx.RequestError as e:
            ctx.set_error(str(e))
            return _err(502, f"Zoekt 不可达: {e}")
        except Exception as e:
            ctx.set_error(str(e))
            logger.error("api_get_file_content error: %s", e)
            return _err(500, str(e))


async def api_projects(request: Request) -> JSONResponse:
    from config import list_projects
    return _ok(list_projects())


# ─── Lifespan ─────────────────────────────────────────

@contextlib.asynccontextmanager
async def lifespan(app):
    setup_audit_logger("http")
    start_audit_listener()
    logger.info("SourcePilot HTTP API starting")

    import config
    summary_task = None
    if config.AUDIT_ENABLED and config.AUDIT_SUMMARY_INTERVAL > 0:
        summary_task = asyncio.create_task(audit_stats.periodic_summary())

    try:
        yield
    finally:
        if summary_task is not None:
            summary_task.cancel()
            try:
                await summary_task
            except asyncio.CancelledError:
                pass
        stop_audit_listener()
        logger.info("SourcePilot HTTP API stopped")


# ─── App ─────────────────────────────────────────────

app = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/api/health", health, methods=["GET"]),
        Route("/api/projects", api_projects, methods=["GET"]),
        Route("/api/search", api_search, methods=["POST"]),
        Route("/api/search_symbol", api_search_symbol, methods=["POST"]),
        Route("/api/search_file", api_search_file, methods=["POST"]),
        Route("/api/search_regex", api_search_regex, methods=["POST"]),
        Route("/api/list_repos", api_list_repos, methods=["POST"]),
        Route("/api/get_file_content", api_get_file_content, methods=["POST"]),
    ],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=9000)
