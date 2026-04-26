"""GET /api/search?q= — substring search over payload_json."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import config
from .deps import get_db, run_sql

router = APIRouter()


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(config.SEARCH_LIMIT_DEFAULT, ge=1, le=config.SEARCH_LIMIT_MAX),
    conn=Depends(get_db),
):
    if not q.strip():
        raise HTTPException(400, "q required")

    def query():
        # Escape LIKE wildcards so user input is treated as a literal substring.
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        rows = conn.execute(
            "SELECT trace_id, MAX(ts_ms) AS last_ms"
            " FROM events"
            " WHERE trace_id != '' AND payload_json LIKE ? ESCAPE '\\'"
            " GROUP BY trace_id"
            " ORDER BY last_ms DESC"
            " LIMIT ?",
            (like, limit),
        ).fetchall()
        return {
            "q": q,
            "limit": limit,
            "trace_ids": [r["trace_id"] for r in rows],
            "results": [
                {"trace_id": r["trace_id"], "last_ts_ms": r["last_ms"]} for r in rows
            ],
        }

    return await run_sql(query)
