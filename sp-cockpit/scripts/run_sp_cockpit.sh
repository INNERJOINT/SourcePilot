#!/usr/bin/env bash
# Launch sp-cockpit (FastAPI on 0.0.0.0:9100).
set -euo pipefail
cd "$(dirname "$0")/.."

: "${SP_COCKPIT_AUDIT_LOG_PATH:=../audit.log}"
: "${SP_COCKPIT_AUDIT_DB_PATH:=./data/audit.db}"
: "${SP_COCKPIT_HOST:=0.0.0.0}"
: "${SP_COCKPIT_PORT:=9100}"
: "${SP_COCKPIT_FRONTEND_DIST:=./frontend/dist}"

mkdir -p "$(dirname "$SP_COCKPIT_AUDIT_DB_PATH")"
export SP_COCKPIT_AUDIT_LOG_PATH SP_COCKPIT_AUDIT_DB_PATH SP_COCKPIT_HOST SP_COCKPIT_PORT SP_COCKPIT_FRONTEND_DIST

exec python -m sp_cockpit.main
