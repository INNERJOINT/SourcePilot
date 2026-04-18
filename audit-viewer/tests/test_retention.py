"""AC7: retention deletes events older than 30 days."""
from __future__ import annotations

import time

from audit_viewer import db as dbmod
from audit_viewer.retention import Retention


def test_30d_cutoff(tmp_paths):
    db_p = tmp_paths["db"]
    conn = dbmod.open_and_bootstrap(db_p)
    now_ms = int(time.time() * 1000)
    old_ms = now_ms - 31 * 86400 * 1000
    edge_ms = now_ms - 29 * 86400 * 1000
    rows = [
        (old_ms, "old", "tool_call", 1.0, "ok", 0, None, None, None, "{}"),
        (old_ms, "old", "tool_call", 1.0, "ok", 0, None, None, None, "{}"),
        (edge_ms, "edge", "tool_call", 1.0, "ok", 0, None, None, None, "{}"),
        (now_ms, "new", "tool_call", 1.0, "ok", 0, None, None, None, "{}"),
    ]
    conn.executemany(
        "INSERT INTO events(ts_ms,trace_id,event,duration_ms,status,slow,tool,stage,interface,payload_json)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()

    r = Retention(db_path=db_p, retention_days=30, interval_s=3600)
    deleted = r.run_once(now_ms=now_ms)
    assert deleted == 2

    conn = dbmod.connect(db_p)
    remaining = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
    assert remaining == 2
    conn.close()
    r.close()


def test_no_deletion_when_nothing_old(tmp_paths):
    db_p = tmp_paths["db"]
    conn = dbmod.open_and_bootstrap(db_p)
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO events(ts_ms,trace_id,event,duration_ms,status,slow,payload_json)"
        " VALUES(?,?,?,?,?,?,?)",
        (now_ms, "t", "tool_call", 1.0, "ok", 0, "{}"),
    )
    conn.commit()
    conn.close()
    r = Retention(db_path=db_p, retention_days=30)
    assert r.run_once(now_ms=now_ms) == 0
    r.close()
