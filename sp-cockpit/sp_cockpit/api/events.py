"""GET /api/events with filters and pagination."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from .deps import get_db, row_to_dict, run_sql

router = APIRouter()


@router.get("/events")
async def events(
    tool: str | None = Query(None),
    status: str | None = Query(None),
    slow: bool | None = Query(None),
    event: str | None = Query(None),
    from_ms: int | None = Query(None),
    to_ms: int | None = Query(None),
    trace_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn=Depends(get_db),
):
    where = []
    params: list = []
    if tool is not None:
        where.append("tool = ?")
        params.append(tool)
    if status is not None:
        where.append("status = ?")
        params.append(status)
    if slow is not None:
        where.append("slow = ?")
        params.append(1 if slow else 0)
    if event is not None:
        where.append("event = ?")
        params.append(event)
    if trace_id is not None:
        where.append("trace_id = ?")
        params.append(trace_id)
    if from_ms is not None:
        where.append("ts_ms >= ?")
        params.append(from_ms)
    if to_ms is not None:
        where.append("ts_ms < ?")
        params.append(to_ms)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    def query():
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM events {where_sql}", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"SELECT id, ts_ms, trace_id, event, duration_ms, status, slow, tool, stage, interface, payload_json"
            f" FROM events {where_sql}"
            f" ORDER BY ts_ms DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [row_to_dict(r) for r in rows],
        }

    return await run_sql(query)
