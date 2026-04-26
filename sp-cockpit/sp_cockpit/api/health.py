"""GET /api/health"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .deps import get_db, run_sql

router = APIRouter()


@router.get("/health")
async def health(conn=Depends(get_db)):
    def query():
        row = conn.execute(
            "SELECT COUNT(*) AS c, COALESCE(MAX(ts_ms), 0) AS latest FROM events"
        ).fetchone()
        return {"db_event_count": row["c"], "latest_event_ts_ms": row["latest"]}

    info = await run_sql(query)
    return {"status": "ok", **info}
