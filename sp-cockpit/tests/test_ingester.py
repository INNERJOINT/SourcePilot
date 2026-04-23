"""Ingester tests: AC1, AC2, AC10, AC12, AC15."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from sp_cockpit.ingester import Ingester, find_rotations
from tests.conftest import make_line


def _count(db_p: Path) -> int:
    from sp_cockpit import db as dbmod
    conn = dbmod.connect(db_p)
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
    finally:
        conn.close()


def test_ac1_freshness(tmp_paths):
    """AC1: a new line is queryable within ≤5s."""
    log_p, db_p = tmp_paths["log"], tmp_paths["db"]
    ing = Ingester(log_path=log_p, db_path=db_p, poll_ms=100)
    log_p.write_text(make_line(trace_id="fresh"))
    start = time.monotonic()
    n = ing.run_once()
    elapsed = time.monotonic() - start
    assert n == 1
    assert elapsed < 5.0
    assert _count(db_p) == 1
    ing.close()


def test_ac2_restart_resume(tmp_paths):
    """AC2: restart resumes without duplication or loss."""
    log_p, db_p = tmp_paths["log"], tmp_paths["db"]
    log_p.write_text("".join(make_line(trace_id=f"t{i}") for i in range(100)))
    ing = Ingester(log_path=log_p, db_path=db_p, poll_ms=100)
    assert ing.run_once() == 100
    ing.close()
    ing2 = Ingester(log_path=log_p, db_path=db_p, poll_ms=100)
    assert ing2.run_once() == 0  # no duplication
    assert _count(db_p) == 100
    # append more, ensure incremental
    with open(log_p, "a") as f:
        for i in range(100, 110):
            f.write(make_line(trace_id=f"t{i}"))
    assert ing2.run_once() == 10
    assert _count(db_p) == 110
    ing2.close()


def test_ac10_rotation_no_loss(tmp_paths):
    """AC10: single rotation does not lose any lines."""
    log_p, db_p = tmp_paths["log"], tmp_paths["db"]
    log_p.write_text("".join(make_line(trace_id=f"a{i}") for i in range(5)))
    ing = Ingester(log_path=log_p, db_path=db_p, poll_ms=100)
    assert ing.run_once() == 5
    rotated = log_p.with_suffix(log_p.suffix + ".1")
    log_p.rename(rotated)
    log_p.write_text("".join(make_line(trace_id=f"b{i}") for i in range(5)))
    ing.run_once()
    assert _count(db_p) == 10
    ing.close()


def test_ac10_multi_rotation_drain(tmp_paths):
    """AC10 (extended): multi-rotation drain across .1 → .2 chain."""
    log_p, db_p = tmp_paths["log"], tmp_paths["db"]
    log_p.write_text(make_line(trace_id="r0"))
    ing = Ingester(log_path=log_p, db_path=db_p, poll_ms=100)
    ing.run_once()
    # rotation 1: current → .1; new current with r1
    log_p.rename(log_p.with_suffix(log_p.suffix + ".1"))
    log_p.write_text(make_line(trace_id="r1"))
    # rotation 2: .1 → .2, current → .1; new current with r2
    p1 = Path(str(log_p) + ".1")
    p1.rename(str(log_p) + ".2")
    log_p.rename(log_p.with_suffix(log_p.suffix + ".1"))
    log_p.write_text(make_line(trace_id="r2"))
    ing.run_once()
    assert _count(db_p) == 3, f"expected 3 events from r0/r1/r2, got {_count(db_p)}"
    ing.close()


def test_ac12_readonly_open(tmp_paths, monkeypatch):
    """AC12: backend opens audit.log only with O_RDONLY (no write flags)."""
    log_p, db_p = tmp_paths["log"], tmp_paths["db"]
    log_p.write_text(make_line(trace_id="ro"))

    captured = []
    real_open = os.open

    def spy_open(path, flags, *args, **kwargs):
        if str(path).endswith("audit.log") or ".log" in str(path):
            captured.append((str(path), flags))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr("os.open", spy_open)

    ing = Ingester(log_path=log_p, db_path=db_p, poll_ms=100)
    ing.run_once()
    ing.close()

    assert captured, "expected at least one open() of the log file"
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
    for path, flags in captured:
        assert (flags & write_flags) == 0, f"log opened with write flag: {path} flags={flags}"


def test_ac15_sigterm_drains_batch(tmp_paths):
    """AC15: stop_event triggers final drain before exit."""
    log_p, db_p = tmp_paths["log"], tmp_paths["db"]
    stop = threading.Event()
    ing = Ingester(log_path=log_p, db_path=db_p, poll_ms=100, stop_event=stop)
    t = threading.Thread(target=ing.run_forever, daemon=True)
    t.start()
    time.sleep(0.2)
    log_p.write_text(make_line(trace_id="last"))
    time.sleep(0.3)
    stop.set()
    t.join(timeout=2.0)
    assert not t.is_alive(), "ingester did not stop within grace window"
    assert _count(db_p) >= 1
    ing.close()


def test_partial_line_does_not_advance_offset(tmp_paths):
    log_p, db_p = tmp_paths["log"], tmp_paths["db"]
    full_line = make_line(trace_id="p")
    log_p.write_text(full_line + full_line[:30])  # second line has no newline
    ing = Ingester(log_path=log_p, db_path=db_p, poll_ms=100)
    n = ing.run_once()
    assert n == 1, f"only complete line should be ingested, got {n}"
    # complete the partial
    with open(log_p, "a") as f:
        f.write(full_line[30:])
    n2 = ing.run_once()
    assert n2 == 1
    assert _count(db_p) == 2
    ing.close()


def test_find_rotations_handles_missing_anchor(tmp_paths):
    """If no rotated file matches anchor inode, returns empty (nothing to drain)."""
    log_p = tmp_paths["log"]
    log_p.write_text("x")
    plans = find_rotations(log_p, max_n=5, anchor_inode=999999999)
    assert plans == []
