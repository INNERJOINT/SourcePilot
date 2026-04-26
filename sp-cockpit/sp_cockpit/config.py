"""Configuration via environment variables."""
import os
from pathlib import Path

SP_COCKPIT_AUDIT_LOG_PATH = Path(os.getenv("SP_COCKPIT_AUDIT_LOG_PATH", "audit.log")).resolve()
SP_COCKPIT_AUDIT_DB_PATH = Path(os.getenv("SP_COCKPIT_AUDIT_DB_PATH", "audit.db")).resolve()

SP_COCKPIT_HOST = os.getenv("SP_COCKPIT_HOST", "0.0.0.0")
SP_COCKPIT_PORT = int(os.getenv("SP_COCKPIT_PORT", "9100"))

RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "30"))
RETENTION_INTERVAL_S = int(os.getenv("RETENTION_INTERVAL_S", "3600"))

POLL_MS = int(os.getenv("POLL_MS", "500"))
ROTATION_MAX_N = int(os.getenv("ROTATION_MAX_N", "5"))

SHUTDOWN_GRACE_S = float(os.getenv("SHUTDOWN_GRACE_S", "2.0"))

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "SP_COCKPIT_CORS_ORIGINS",
        "http://localhost:9100,http://127.0.0.1:9100,http://localhost:5173",
    ).split(",")
    if o.strip()
]

FRONTEND_DIST = Path(
    os.getenv("SP_COCKPIT_FRONTEND_DIST", str(Path(__file__).parent.parent / "frontend" / "dist"))
).resolve()

SEARCH_LIMIT_DEFAULT = 50
SEARCH_LIMIT_MAX = 200
SEARCH_TIMEOUT_S = 2.0

SP_COCKPIT_INDEXING_DB_PATH = Path(os.getenv("SP_COCKPIT_INDEXING_DB_PATH", "indexing.db")).resolve()
INDEXING_INTERNAL_TOKEN = os.getenv("INDEXING_INTERNAL_TOKEN", "")
