"""SQLite connection helper and schema bootstrap for the indexing metadata DB."""
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from . import config


class JobLockConflict(Exception):
    """Raised when a running job already exists for (repo, backend)."""

    def __init__(self, existing_job_id: int) -> None:
        self.existing_job_id = existing_job_id
        super().__init__(f"Running job {existing_job_id} already exists")

CURRENT_SCHEMA_VERSION = "2"
SCHEMA_FILE = Path(__file__).parent / "indexing_schema.sql"


def connect(db_path: "Path | str | None" = None) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode and sane pragmas."""
    path = Path(db_path) if db_path is not None else config.SP_COCKPIT_INDEXING_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def bootstrap(conn: sqlite3.Connection) -> None:
    """Create schema idempotently, run migrations, and stamp schema_version."""
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    conn.executescript(sql)
    # Migration v1 → v2: add project column and update UNIQUE constraint
    cols = [row[1] for row in conn.execute("PRAGMA table_info(index_repos)").fetchall()]
    if "project" not in cols:
        conn.executescript("""
            CREATE TABLE index_repos_new (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              repo_path   TEXT    NOT NULL,
              project     TEXT,
              created_at  INTEGER NOT NULL DEFAULT (strftime('%s','now') * 1000),
              archived_at INTEGER,
              UNIQUE(repo_path, project)
            );
            INSERT INTO index_repos_new(id, repo_path, created_at, archived_at)
                SELECT id, repo_path, created_at, archived_at FROM index_repos;
            DROP TABLE index_repos;
            ALTER TABLE index_repos_new RENAME TO index_repos;
        """)
    set_meta(conn, "schema_version", CURRENT_SCHEMA_VERSION)
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM indexing_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO indexing_meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def open_and_bootstrap(db_path: "Path | str | None" = None) -> sqlite3.Connection:
    """Convenience: connect + bootstrap."""
    conn = connect(db_path)
    bootstrap(conn)
    return conn


# ---------------------------------------------------------------------------
# Repo helpers
# ---------------------------------------------------------------------------

def upsert_repo(conn: sqlite3.Connection, repo_path: str, project: Optional[str] = None) -> int:
    """Insert repo if not exists; return its id."""
    conn.execute(
        "INSERT INTO index_repos(repo_path, project) VALUES(?, ?) "
        "ON CONFLICT(repo_path, project) DO NOTHING",
        (repo_path, project),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM index_repos WHERE repo_path = ? AND project IS ?",
        (repo_path, project),
    ).fetchone()
    return row["id"]


def archive_repo(conn: sqlite3.Connection, repo_id: int, ts_ms: Optional[int] = None) -> None:
    """Set archived_at for a repo."""
    if ts_ms is None:
        import time
        ts_ms = int(time.time() * 1000)
    conn.execute("UPDATE index_repos SET archived_at = ? WHERE id = ?", (ts_ms, repo_id))
    conn.commit()


def get_repo(conn: sqlite3.Connection, repo_path: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM index_repos WHERE repo_path = ?", (repo_path,)
    ).fetchone()


# ---------------------------------------------------------------------------
# Job helpers
# ---------------------------------------------------------------------------

def create_job(
    conn: sqlite3.Connection,
    repo_id: int,
    backend: str,
    entity_count_before: Optional[int] = None,
    log_path: Optional[str] = None,
) -> int:
    """Create a job in 'pending' status; return its id."""
    cur = conn.execute(
        "INSERT INTO index_jobs(repo_id, backend, status, entity_count_before, log_path) "
        "VALUES(?, ?, 'pending', ?, ?)",
        (repo_id, backend, entity_count_before, log_path),
    )
    conn.commit()
    return cur.lastrowid


def start_job(conn: sqlite3.Connection, job_id: int) -> None:
    """Transition job to 'running'."""
    conn.execute(
        "UPDATE index_jobs SET status='running', started_at=strftime('%s','now')*1000 WHERE id=?",
        (job_id,),
    )
    conn.commit()


def finish_job(
    conn: sqlite3.Connection,
    job_id: int,
    status: str,
    exit_code: Optional[int] = None,
    entity_count_after: Optional[int] = None,
) -> None:
    """Transition job to a terminal status."""
    conn.execute(
        "UPDATE index_jobs SET status=?, finished_at=strftime('%s','now')*1000, "
        "exit_code=?, entity_count_after=? WHERE id=?",
        (status, exit_code, entity_count_after, job_id),
    )
    conn.commit()


def get_job(conn: sqlite3.Connection, job_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM index_jobs WHERE id = ?", (job_id,)).fetchone()


def get_running_job(conn: sqlite3.Connection, repo_id: int, backend: str) -> Optional[sqlite3.Row]:
    """Return the running job for repo+backend if one exists (uses singleton index)."""
    return conn.execute(
        "SELECT * FROM index_jobs WHERE repo_id=? AND backend=? AND status='running'",
        (repo_id, backend),
    ).fetchone()


# ---------------------------------------------------------------------------
# High-level API helpers
# ---------------------------------------------------------------------------

def create_job_for_path(
    conn: sqlite3.Connection,
    repo_path: str,
    backend: str,
    log_path: Optional[str] = None,
    project: Optional[str] = None,
) -> int:
    """Upsert repo, create a running job, return job_id.

    Raises JobLockConflict if a running job already exists for (repo, backend).
    """
    repo_id = upsert_repo(conn, repo_path, project)
    existing = get_running_job(conn, repo_id, backend)
    if existing is not None:
        raise JobLockConflict(existing["id"])
    cur = conn.execute(
        "INSERT INTO index_jobs(repo_id, backend, status, log_path) VALUES(?, ?, 'running', ?)",
        (repo_id, backend, log_path),
    )
    conn.commit()
    return cur.lastrowid


def list_repos(
    conn: sqlite3.Connection,
    backend_filter: Optional[str] = None,
    status_filter: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return repos joined with their most recent job per (repo, backend)."""
    where: list[str] = []
    params: list = []
    if backend_filter:
        where.append("j.backend = ?")
        params.append(backend_filter)
    if status_filter:
        where.append("j.status = ?")
        params.append(status_filter)
    where_sql = ("AND " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT r.id, r.id AS repo_id, r.repo_path, r.created_at, r.archived_at,
               j.id AS job_id, j.backend, j.status, j.started_at, j.finished_at,
               j.exit_code, j.entity_count_after, j.log_path
        FROM index_repos r
        LEFT JOIN index_jobs j ON j.id = (
            SELECT id FROM index_jobs
            WHERE repo_id = r.id
            {where_sql}
            ORDER BY started_at DESC LIMIT 1
        )
        ORDER BY r.id DESC
    """
    rows = conn.execute(sql, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        # Compute derived fields expected by the frontend
        started = d.get("started_at")
        finished = d.get("finished_at")
        duration_s = None
        if started and finished:
            duration_s = round((finished - started) / 1000, 1)
        d["last_finished_at"] = finished
        d["last_started_at"] = started
        d["last_duration_s"] = duration_s
        d["last_status"] = d.get("status")
        d["entity_count"] = d.get("entity_count_after")
        result.append(d)
    return result


def get_repo_detail(
    conn: sqlite3.Connection,
    repo_id: int,
    limit: int = 10,
) -> Optional[dict[str, Any]]:
    """Return repo info + recent jobs list."""
    repo_row = conn.execute("SELECT * FROM index_repos WHERE id = ?", (repo_id,)).fetchone()
    if repo_row is None:
        return None
    jobs = conn.execute(
        "SELECT * FROM index_jobs WHERE repo_id = ? ORDER BY started_at DESC LIMIT ?",
        (repo_id, limit),
    ).fetchall()
    return {
        "repo": dict(repo_row),
        "jobs": [dict(j) for j in jobs],
    }


def delete_repo(
    conn: sqlite3.Connection,
    repo_id: int,
    backend: Optional[str] = None,
) -> None:
    """Delete jobs for a repo (optionally filtered by backend).

    Archives the repo if no jobs remain.
    """
    if backend:
        conn.execute(
            "DELETE FROM index_jobs WHERE repo_id = ? AND backend = ?",
            (repo_id, backend),
        )
    else:
        conn.execute("DELETE FROM index_jobs WHERE repo_id = ?", (repo_id,))
    remaining = conn.execute(
        "SELECT COUNT(*) FROM index_jobs WHERE repo_id = ?", (repo_id,)
    ).fetchone()[0]
    if remaining == 0:
        ts_ms = int(time.time() * 1000)
        conn.execute(
            "UPDATE index_repos SET archived_at = ? WHERE id = ? AND archived_at IS NULL",
            (ts_ms, repo_id),
        )
    conn.commit()


def reap_stale(conn: sqlite3.Connection, older_than_hours: float = 2.0) -> int:
    """Mark stuck running jobs as 'warn'. Returns count updated."""
    cutoff_ms = int((time.time() - older_than_hours * 3600) * 1000)
    cur = conn.execute(
        "UPDATE index_jobs SET status='warn', finished_at=? "
        "WHERE status='running' AND started_at < ?",
        (int(time.time() * 1000), cutoff_ms),
    )
    conn.commit()
    return cur.rowcount


def init_schema(db_path: "Path | str | None" = None) -> None:
    """Init schema idempotently (convenience wrapper used by main.py startup)."""
    conn = open_and_bootstrap(db_path)
    conn.close()
    # reap_stale is called separately; this function is pure schema bootstrap.
