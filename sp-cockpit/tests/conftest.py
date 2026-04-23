"""Shared pytest fixtures."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Make sp_cockpit importable when running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def tmp_paths(tmp_path: Path, monkeypatch):
    log_p = tmp_path / "audit.log"
    db_p = tmp_path / "audit.db"
    log_p.touch()
    monkeypatch.setenv("SP_COCKPIT_AUDIT_LOG_PATH", str(log_p))
    monkeypatch.setenv("SP_COCKPIT_AUDIT_DB_PATH", str(db_p))
    monkeypatch.setenv("SP_COCKPIT_FRONTEND_DIST", "/nonexistent-spa")
    # Reload config so env vars take effect for any module that already imported it.
    import importlib

    from sp_cockpit import config as cfg

    importlib.reload(cfg)
    yield {"log": log_p, "db": db_p, "tmp": tmp_path}


def make_line(
    *,
    ts: str = "2026-04-18T12:00:00.123",
    trace_id: str = "t1",
    event: str = "tool_call",
    duration_ms: float = 1.0,
    status: str = "ok",
    slow: bool = False,
    tool: str | None = None,
    stage: str | None = None,
    interface: str | None = None,
    extra: dict | None = None,
) -> str:
    obj = {
        "timestamp": ts,
        "trace_id": trace_id,
        "event": event,
        "duration_ms": duration_ms,
        "status": status,
        "slow": slow,
    }
    if tool:
        obj["tool"] = tool
    if stage:
        obj["stage"] = stage
    if interface:
        obj["interface"] = interface
    if extra:
        obj.update(extra)
    return json.dumps(obj) + "\n"


@pytest.fixture
def seeded_db(tmp_paths):
    """Seed a small mixed-event DB and return paths."""
    from sp_cockpit import db as dbmod

    conn = dbmod.open_and_bootstrap(tmp_paths["db"])
    now_ms = int(time.time() * 1000)
    rows = [
        (now_ms - 1000, "t1", "tool_call", 10.0, "ok", 0, "search_code", None, "mcp", "{}"),
        (now_ms - 800, "t1", "pipeline_stage", 5.0, "ok", 0, None, "classify", None, "{}"),
        (now_ms - 600, "t1", "pipeline_stage", 250.0, "ok", 1, None, "rewrite", None, "{}"),
        (now_ms - 400, "t2", "tool_call", 50.0, "error", 0, "search_symbol", None, "mcp", "{}"),
        (now_ms - 200, "", "audit_summary", 0.0, "ok", 0, None, None, None, '{"per_tool":{}}'),
    ]
    conn.executemany(
        "INSERT INTO events(ts_ms,trace_id,event,duration_ms,status,slow,tool,stage,interface,payload_json)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return tmp_paths


@pytest.fixture
def client(tmp_paths):
    """FastAPI TestClient bound to the temp DB."""
    import importlib

    from sp_cockpit.api import app as app_mod
    from sp_cockpit.api import deps as deps_mod
    from sp_cockpit import config as cfg

    importlib.reload(cfg)
    importlib.reload(deps_mod)
    importlib.reload(app_mod)

    from fastapi.testclient import TestClient

    return TestClient(app_mod.create_app())


@pytest.fixture
def big_db(tmp_paths):
    """Seed 100k events for latency assertions."""
    from sp_cockpit import db as dbmod

    conn = dbmod.open_and_bootstrap(tmp_paths["db"])
    now_ms = int(time.time() * 1000)
    rows = []
    tools = ["search_code", "search_symbol", "search_file", "search_regex"]
    for i in range(100_000):
        ts = now_ms - (100_000 - i) * 10  # spread across ~16 minutes
        tid = f"trace_{i // 5}"
        is_err = 1 if i % 97 == 0 else 0
        is_slow = 1 if i % 53 == 0 else 0
        rows.append((
            ts, tid, "tool_call", float(5 + (i % 200)),
            "error" if is_err else "ok", is_slow, tools[i % 4], None, "mcp", "{}"
        ))
    conn.executemany(
        "INSERT INTO events(ts_ms,trace_id,event,duration_ms,status,slow,tool,stage,interface,payload_json)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return tmp_paths
