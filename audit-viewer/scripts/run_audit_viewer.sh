#!/usr/bin/env bash
# Launch audit-viewer (FastAPI on 0.0.0.0:9100).
set -euo pipefail
cd "$(dirname "$0")/.."

: "${AUDIT_LOG_PATH:=../audit.log}"
: "${AUDIT_DB_PATH:=./data/audit.db}"
: "${AUDIT_VIEWER_HOST:=0.0.0.0}"
: "${AUDIT_VIEWER_PORT:=9100}"
: "${AUDIT_VIEWER_FRONTEND_DIST:=./frontend/dist}"

mkdir -p "$(dirname "$AUDIT_DB_PATH")"
export AUDIT_LOG_PATH AUDIT_DB_PATH AUDIT_VIEWER_HOST AUDIT_VIEWER_PORT AUDIT_VIEWER_FRONTEND_DIST

exec python -m audit_viewer.main
