"""SQLite connection helper, schema bootstrap, migrations."""
import sqlite3
from pathlib import Path

from . import config

CURRENT_SCHEMA_VERSION = "1"
SCHEMA_FILE = Path(__file__).parent / "schema.sql"


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode and sane pragmas."""
    path = Path(db_path) if db_path is not None else config.AUDIT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def bootstrap(conn: sqlite3.Connection) -> None:
    """Create schema idempotently and stamp schema_version."""
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    conn.executescript(sql)
    set_meta(conn, "schema_version", CURRENT_SCHEMA_VERSION)
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def migrate(conn: sqlite3.Connection, from_version: str, to_version: str) -> None:
    """Schema migration entrypoint stub. v1 ships fresh schema; future versions add upgrade fns."""
    if from_version == to_version:
        return
    raise NotImplementedError(
        f"Migration from {from_version} to {to_version} not implemented."
    )


def open_and_bootstrap(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Convenience: connect + bootstrap + run migration if needed."""
    conn = connect(db_path)
    bootstrap(conn)
    current = get_meta(conn, "schema_version")
    if current and current != CURRENT_SCHEMA_VERSION:
        migrate(conn, current, CURRENT_SCHEMA_VERSION)
        set_meta(conn, "schema_version", CURRENT_SCHEMA_VERSION)
        conn.commit()
    return conn
