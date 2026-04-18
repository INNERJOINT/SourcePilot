"""Tail audit.log into SQLite. Polling loop with multi-rotation drain."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import config, db
from .parser import parse_line

log = logging.getLogger(__name__)


@dataclass
class DrainPlan:
    path: Path
    start_offset: int


def find_rotations(
    current_path: Path, max_n: int, anchor_inode: int | None
) -> list[DrainPlan]:
    """Return ordered drain plan for rotated siblings.

    RotatingFileHandler renames .4→.5, .3→.4, .2→.3, .1→.2, current→.1.
    So the file we were reading (anchor_inode) is now at some .N.
    Drain plan:
      1. The file matching anchor_inode → drain from saved offset to EOF.
      2. Any file with a LOWER number (newer) than the anchor → drain from offset 0.
      3. Files with HIGHER number (older) than the anchor → already drained, skip.
    Returns list ordered oldest → newest (so events insert in chronological order).
    """
    if anchor_inode is None:
        return []
    rotated: list[tuple[int, Path, int]] = []
    for n in range(1, max_n + 1):
        p = current_path.with_suffix(current_path.suffix + f".{n}")
        if not p.exists():
            continue
        try:
            ino = os.stat(p).st_ino
        except FileNotFoundError:
            continue
        rotated.append((n, p, ino))
    anchor_n: int | None = None
    for n, _p, ino in rotated:
        if ino == anchor_inode:
            anchor_n = n
            break
    if anchor_n is None:
        return []
    plans: list[DrainPlan] = []
    plans.append(DrainPlan(path=next(p for n, p, _ in rotated if n == anchor_n), start_offset=-1))
    for n, p, _ino in rotated:
        if n < anchor_n:
            plans.append(DrainPlan(path=p, start_offset=0))
    plans.sort(key=lambda dp: -_n_for(dp.path))
    return plans


def _n_for(p: Path) -> int:
    suffix = p.name.rsplit(".", 1)[-1]
    try:
        return int(suffix)
    except ValueError:
        return 0


class Ingester:
    """Polling-tail ingester with persistent (inode, offset) and rotation handling."""

    def __init__(
        self,
        log_path: Path | None = None,
        db_path: Path | None = None,
        poll_ms: int | None = None,
        max_rotations: int | None = None,
        stop_event: threading.Event | None = None,
    ):
        self.log_path = Path(log_path) if log_path else config.AUDIT_LOG_PATH
        self.db_path = Path(db_path) if db_path else config.AUDIT_DB_PATH
        self.poll_s = (poll_ms if poll_ms is not None else config.POLL_MS) / 1000.0
        self.max_rotations = max_rotations or config.ROTATION_MAX_N
        self.stop_event = stop_event or threading.Event()
        self._conn = db.open_and_bootstrap(self.db_path)
        self._inode: int | None = self._read_inode()
        self._offset: int = self._read_offset()

    def _read_inode(self) -> int | None:
        v = db.get_meta(self._conn, "ingester_inode")
        return int(v) if v else None

    def _read_offset(self) -> int:
        v = db.get_meta(self._conn, "ingester_offset")
        return int(v) if v else 0

    def _persist_state(self) -> None:
        db.set_meta(self._conn, "ingester_inode", str(self._inode) if self._inode else "")
        db.set_meta(self._conn, "ingester_offset", str(self._offset))

    def _insert_batch(self, rows: list[dict]) -> None:
        if not rows:
            return
        self._conn.executemany(
            "INSERT INTO events"
            "(ts_ms, trace_id, event, duration_ms, status, slow, tool, stage, interface, payload_json)"
            " VALUES (:ts_ms,:trace_id,:event,:duration_ms,:status,:slow,:tool,:stage,:interface,:payload_json)",
            rows,
        )

    def _drain_file(self, path: Path, start_offset: int) -> int:
        """Read complete lines from path starting at start_offset; insert; return new offset."""
        rows: list[dict] = []
        # Read-only — assert by passing 'rb' explicitly
        flags = os.O_RDONLY
        fd = os.open(path, flags)
        try:
            os.lseek(fd, start_offset, os.SEEK_SET)
            with os.fdopen(fd, "rb", closefd=False) as f:
                buf = f.read()
            offset = start_offset + len(buf)
            text = buf.decode("utf-8", errors="replace")
            ends_clean = text.endswith("\n")
            lines = text.splitlines(keepends=True)
            consumed = 0
            for line in lines:
                if not line.endswith("\n"):
                    # partial trailing line — back off offset, retry next tick
                    break
                row = parse_line(line)
                if row is not None:
                    rows.append(row)
                consumed += len(line.encode("utf-8"))
            new_offset = start_offset + consumed if not ends_clean else offset
            self._insert_batch(rows)
            return new_offset
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    def run_once(self) -> int:
        """One polling tick. Returns number of events inserted."""
        try:
            st = os.stat(self.log_path)
        except FileNotFoundError:
            return 0
        before_count = self._conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
        if self._inode is not None and st.st_ino != self._inode:
            # rotation detected — drain rotated siblings first
            plans = find_rotations(self.log_path, self.max_rotations, self._inode)
            for plan in plans:
                start = self._offset if plan.start_offset == -1 else plan.start_offset
                new_off = self._drain_file(plan.path, start)
                # if anchor was incompletely drained, keep offset; else move on
                self._offset = new_off if plan.start_offset == -1 else self._offset
            self._inode = st.st_ino
            self._offset = 0
        elif self._inode is None:
            self._inode = st.st_ino
            self._offset = 0
        # drain current
        new_off = self._drain_file(self.log_path, self._offset)
        self._offset = new_off
        self._persist_state()
        self._conn.commit()
        after_count = self._conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
        return after_count - before_count

    def run_forever(self) -> None:
        log.info("Ingester started: %s -> %s", self.log_path, self.db_path)
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("Ingester tick failed")
            self.stop_event.wait(self.poll_s)
        # final drain
        try:
            self.run_once()
        except Exception:
            log.exception("Ingester final drain failed")
        log.info("Ingester stopped")

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# Strict read-only open helper used by AC12 test (mockable).
def open_readonly(path: Path) -> int:
    return os.open(path, os.O_RDONLY)


__all__ = ["Ingester", "DrainPlan", "find_rotations", "open_readonly"]


# Convenience for ad-hoc use
def _cli() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ing = Ingester()
    try:
        ing.run_forever()
    finally:
        ing.close()


if __name__ == "__main__":
    _cli()


# Helpers ---------------------------------------------------------------
def event_count(db_path: Path | str) -> int:
    """Helper for tests: open db and return total event count."""
    conn = db.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
    finally:
        conn.close()


# Re-export json for tests that build canonical lines
__all__.append("event_count")
__all__.append("json")
