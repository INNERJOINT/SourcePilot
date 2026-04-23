"""Hourly retention loop: delete events older than RETENTION_DAYS."""
from __future__ import annotations

import logging
import threading
import time

from . import config, db

log = logging.getLogger(__name__)


class Retention:
    def __init__(
        self,
        db_path=None,
        retention_days: int | None = None,
        interval_s: int | None = None,
        stop_event: threading.Event | None = None,
    ):
        self.db_path = db_path or config.SP_COCKPIT_AUDIT_DB_PATH
        self.retention_days = retention_days if retention_days is not None else config.RETENTION_DAYS
        self.interval_s = interval_s if interval_s is not None else config.RETENTION_INTERVAL_S
        self.stop_event = stop_event or threading.Event()
        self._conn = db.open_and_bootstrap(self.db_path)

    def cutoff_ms(self, now_ms: int | None = None) -> int:
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        return now_ms - self.retention_days * 86400 * 1000

    def run_once(self, now_ms: int | None = None) -> int:
        cutoff = self.cutoff_ms(now_ms)
        cur = self._conn.execute("DELETE FROM events WHERE ts_ms < ?", (cutoff,))
        deleted = cur.rowcount
        self._conn.commit()
        if deleted > 0:
            log.info("Retention deleted %d events older than %d days", deleted, self.retention_days)
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                log.exception("WAL checkpoint failed")
        return deleted

    def run_forever(self) -> None:
        log.info("Retention started: %d days, interval %ds", self.retention_days, self.interval_s)
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("Retention cycle failed")
            self.stop_event.wait(self.interval_s)
        log.info("Retention stopped")

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
