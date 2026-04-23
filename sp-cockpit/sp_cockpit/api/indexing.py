"""FastAPI router: /api/indexing/* — index job management endpoints."""
from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from .. import config, indexing_db
from .deps import run_sql

router = APIRouter(prefix="/indexing", tags=["indexing"])

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TriggerJobRequest(BaseModel):
    repo_path: str
    backend: str
    log_path: Optional[str] = None


class InternalStartRequest(BaseModel):
    repo_path: str
    backend: str
    log_path: Optional[str] = None


class InternalFinishRequest(BaseModel):
    status: str
    exit_code: Optional[int] = None
    entity_count_after: Optional[int] = None


# ---------------------------------------------------------------------------
# Internal auth helper
# ---------------------------------------------------------------------------


def _require_internal_token(x_indexing_internal_token: Optional[str]) -> None:
    expected = config.INDEXING_INTERNAL_TOKEN
    if not expected or x_indexing_internal_token != expected:
        raise HTTPException(status_code=403, detail="Invalid or missing X-Indexing-Internal-Token")


# ---------------------------------------------------------------------------
# DB connection helper (per-request, like audit deps.get_db)
# ---------------------------------------------------------------------------


def _get_indexing_conn():
    return indexing_db.open_and_bootstrap()


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@router.get("/repos")
async def list_repos(
    backend: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
) -> dict[str, Any]:
    def _query():
        conn = _get_indexing_conn()
        try:
            return {"items": indexing_db.list_repos(conn, backend_filter=backend, status_filter=status)}
        finally:
            conn.close()

    return await run_sql(_query)


@router.get("/repos/{repo_id}")
async def get_repo(repo_id: int) -> dict[str, Any]:
    def _query():
        conn = _get_indexing_conn()
        try:
            detail = indexing_db.get_repo_detail(conn, repo_id)
            if detail is None:
                return None
            return detail
        finally:
            conn.close()

    result = await run_sql(_query)
    if result is None:
        raise HTTPException(status_code=404, detail="Repo not found")
    return result


@router.post("/jobs", status_code=201)
async def trigger_job(body: TriggerJobRequest) -> dict[str, Any]:
    """Start a new index job. Returns {job_id}. 409 if a job is already running."""
    # Try to import backend trigger — may not exist yet (worker-3 task)
    try:
        from .. import indexing_backends  # type: ignore[import]
        use_backends = True
    except ImportError:
        use_backends = False

    def _run():
        conn = _get_indexing_conn()
        try:
            if use_backends:
                trigger_fn = getattr(indexing_backends, "trigger", None)
                if trigger_fn:
                    trigger_fn(body.repo_path, body.backend)

            job_id = indexing_db.create_job_for_path(
                conn, body.repo_path, body.backend, getattr(body, "log_path", None)
            )
            return {"job_id": job_id, "status": "running"}
        except indexing_db.JobLockConflict as exc:
            return exc
        finally:
            conn.close()

    result = await run_sql(_run)
    if isinstance(result, indexing_db.JobLockConflict):
        raise HTTPException(
            status_code=409,
            detail={"error": "running", "existing_job_id": result.existing_job_id},
        )
    return result


@router.get("/jobs/{job_id}/log")
async def get_job_log(
    job_id: int,
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Read job log from byte offset. eof=true only when job.finished_at is set."""

    def _read():
        conn = _get_indexing_conn()
        try:
            job = indexing_db.get_job(conn, job_id)
            if job is None:
                return None
            log_path = job["log_path"]
            finished_at = job["finished_at"]
        finally:
            conn.close()

        if not log_path or not os.path.exists(log_path):
            return {
                "offset": offset,
                "next_offset": offset,
                "content": "",
                "eof": finished_at is not None,
            }

        with open(log_path, "rb") as f:
            f.seek(offset)
            chunk = f.read(65536)  # 64 KB max per read
            next_offset = offset + len(chunk)

        return {
            "offset": offset,
            "next_offset": next_offset,
            "content": chunk.decode("utf-8", errors="replace"),
            "eof": finished_at is not None,
        }

    result = await run_sql(_read)
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return result


@router.delete("/repos/{repo_id}", status_code=200)
async def delete_repo(
    repo_id: int,
    backend: Optional[str] = Query(None),
) -> dict[str, Any]:
    """Hard-delete repo (and optionally filter by backend). 500 on partial failure."""
    # Try to import backend hard_delete
    try:
        from .. import indexing_backends  # type: ignore[import]
        use_backends = True
    except ImportError:
        use_backends = False

    failed: list[str] = []

    def _run():
        conn = _get_indexing_conn()
        try:
            if use_backends:
                hard_delete_fn = getattr(indexing_backends, "hard_delete", None)
                if hard_delete_fn:
                    try:
                        hard_delete_fn(repo_id, backend)
                    except Exception as exc:
                        failed.append(str(exc))

            if not failed:
                indexing_db.delete_repo(conn, repo_id, backend)
                return {"deleted": True}
            return None
        finally:
            conn.close()

    result = await run_sql(_run)
    if failed:
        raise HTTPException(
            status_code=500,
            detail={"partial": True, "failed": failed},
        )
    return result


# ---------------------------------------------------------------------------
# Internal endpoints (require X-Indexing-Internal-Token)
# ---------------------------------------------------------------------------


@router.post("/jobs/internal-start", status_code=201)
async def internal_start(
    body: InternalStartRequest,
    x_indexing_internal_token: Optional[str] = Header(None),
) -> dict[str, Any]:
    """Internal: start a new job. Used by index wrapper scripts."""
    _require_internal_token(x_indexing_internal_token)

    def _run():
        conn = _get_indexing_conn()
        try:
            job_id = indexing_db.create_job_for_path(
                conn, body.repo_path, body.backend, getattr(body, "log_path", None)
            )
            return {"job_id": job_id, "status": "running"}
        except indexing_db.JobLockConflict as exc:
            return exc
        finally:
            conn.close()

    result = await run_sql(_run)
    if isinstance(result, indexing_db.JobLockConflict):
        raise HTTPException(
            status_code=409,
            detail={"error": "running", "existing_job_id": result.existing_job_id},
        )
    return result


@router.post("/jobs/{job_id}/finish", status_code=200)
async def internal_finish(
    job_id: int,
    body: InternalFinishRequest,
    x_indexing_internal_token: Optional[str] = Header(None),
) -> dict[str, Any]:
    """Internal: mark a job as finished."""
    _require_internal_token(x_indexing_internal_token)

    def _run():
        conn = _get_indexing_conn()
        try:
            job = indexing_db.get_job(conn, job_id)
            if job is None:
                return None
            indexing_db.finish_job(
                conn, job_id, body.status, body.exit_code, body.entity_count_after
            )
            return {"job_id": job_id, "status": body.status}
        finally:
            conn.close()

    result = await run_sql(_run)
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return result
