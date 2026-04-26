"""GET /api/stats?window=1h|6h|24h"""
from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from .deps import get_db, run_sql

router = APIRouter()

WINDOWS = {
    "1h": (3600, 60),
    "6h": (6 * 3600, 5 * 60),
    "24h": (24 * 3600, 15 * 60),
}


@router.get("/stats")
async def stats(
    window: Literal["1h", "6h", "24h"] = Query("1h"),
    conn=Depends(get_db),
):
    if window not in WINDOWS:
        raise HTTPException(400, "invalid window")
    span_s, bucket_s = WINDOWS[window]
    now_ms = int(time.time() * 1000)
    from_ms = now_ms - span_s * 1000
    bucket_ms = bucket_s * 1000

    def query():
        # totals
        total_row = conn.execute(
            "SELECT COUNT(*) AS n,"
            " AVG(duration_ms) AS avg_ms,"
            " SUM(CASE WHEN status != 'ok' THEN 1 ELSE 0 END) AS errs,"
            " SUM(CASE WHEN slow = 1 THEN 1 ELSE 0 END) AS slows"
            " FROM events WHERE ts_ms >= ?",
            (from_ms,),
        ).fetchone()
        n = total_row["n"] or 0
        # percentiles via sorted scan (acceptable up to ~10^6 events)
        durations = [
            r["duration_ms"]
            for r in conn.execute(
                "SELECT duration_ms FROM events WHERE ts_ms >= ? ORDER BY duration_ms",
                (from_ms,),
            )
        ]
        p50 = _percentile(durations, 0.50)
        p95 = _percentile(durations, 0.95)
        qps = n / span_s if span_s else 0.0
        error_rate = (total_row["errs"] or 0) / n if n else 0.0
        slow_ratio = (total_row["slows"] or 0) / n if n else 0.0

        # buckets
        bucket_rows = conn.execute(
            "SELECT (ts_ms / ?) * ? AS bucket,"
            " COUNT(*) AS n,"
            " SUM(CASE WHEN status != 'ok' THEN 1 ELSE 0 END) AS errs,"
            " AVG(duration_ms) AS avg_ms"
            " FROM events WHERE ts_ms >= ?"
            " GROUP BY bucket ORDER BY bucket ASC",
            (bucket_ms, bucket_ms, from_ms),
        ).fetchall()
        # per-bucket p50/p95 — light scan per bucket
        buckets = []
        for br in bucket_rows:
            bd = [
                r["duration_ms"]
                for r in conn.execute(
                    "SELECT duration_ms FROM events WHERE ts_ms >= ? AND ts_ms < ? ORDER BY duration_ms",
                    (br["bucket"], br["bucket"] + bucket_ms),
                )
            ]
            buckets.append({
                "ts_ms": br["bucket"],
                "qps": (br["n"] or 0) / bucket_s,
                "p50_ms": _percentile(bd, 0.50),
                "p95_ms": _percentile(bd, 0.95),
                "errors": br["errs"] or 0,
            })
        return {
            "window": window,
            "from_ms": from_ms,
            "to_ms": now_ms,
            "qps": qps,
            "p50_ms": p50,
            "p95_ms": p95,
            "error_rate": error_rate,
            "slow_ratio": slow_ratio,
            "total_events": n,
            "buckets": buckets,
        }

    return await run_sql(query)


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round(p * (len(sorted_vals) - 1)))))
    return float(sorted_vals[k])
