"""Per-request SQLite connection dependency for FastAPI handlers."""
from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from .. import config, db

T = TypeVar("T")


def get_db():
    """FastAPI dependency yielding a per-request SQLite connection."""
    conn = db.connect(config.SP_COCKPIT_AUDIT_DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


async def run_sql(fn: Callable[..., T], *args, **kwargs) -> T:
    """Run blocking SQL in a worker thread to keep the event loop responsive."""
    return await asyncio.to_thread(fn, *args, **kwargs)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}
