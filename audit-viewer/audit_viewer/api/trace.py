"""GET /api/trace/{trace_id} — chronological events for one trace."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .deps import get_db, row_to_dict, run_sql

router = APIRouter()


@router.get("/trace/{trace_id}")
async def trace_detail(trace_id: str, conn=Depends(get_db)):
    if not trace_id:
        raise HTTPException(400, "trace_id required")

    def query():
        # AC14: exclude empty trace_id matches (audit_summary events)
        rows = conn.execute(
            "SELECT id, ts_ms, trace_id, event, duration_ms, status, slow, tool, stage, interface, payload_json"
            " FROM events WHERE trace_id != '' AND trace_id = ?"
            " ORDER BY ts_ms ASC",
            (trace_id,),
        ).fetchall()
        if not rows:
            return None
        events = [row_to_dict(r) for r in rows]
        started = events[0]["ts_ms"]
        ended = max(e["ts_ms"] + e["duration_ms"] for e in events)
        has_error = any(e["status"] != "ok" for e in events)
        return {
            "trace_id": trace_id,
            "started_ms": started,
            "ended_ms": int(ended),
            "total_ms": int(ended - started),
            "event_count": len(events),
            "has_error": has_error,
            "events": events,
        }

    result = await run_sql(query)
    if result is None:
        raise HTTPException(404, "trace not found")
    return result
