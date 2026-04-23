#!/usr/bin/env bash
# migrate_to_sp_cockpit.sh — one-shot migration from audit-viewer → sp-cockpit
#
# Operations (idempotent — safe to re-run):
#   1. Rewrite legacy env var names in .env to the SP_COCKPIT_* equivalents.
#      Backs up the original to .env.bak (only if .env.bak does not already exist).
#   2. Move audit-viewer/data/ → sp-cockpit/data/ (only if source exists and dest does not).
#
# This script does NOT touch source files, the Python package, scripts, compose,
# CI workflow, or docs — those changes ship in the same commit as this script.

set -euo pipefail

source "$(dirname "$0")/_common.sh"
_common_parse_help "$@"

DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$DIR"

ENV_FILE="$DIR/.env"

# Mapping: OLD_NAME=NEW_NAME (one per line, no spaces)
ENV_MAP=(
    "AUDIT_LOG_PATH=SP_COCKPIT_AUDIT_LOG_PATH"
    "AUDIT_DB_PATH=SP_COCKPIT_AUDIT_DB_PATH"
    "AUDIT_VIEWER_HOST=SP_COCKPIT_HOST"
    "AUDIT_VIEWER_PORT=SP_COCKPIT_PORT"
    "AUDIT_VIEWER_CORS_ORIGINS=SP_COCKPIT_CORS_ORIGINS"
    "AUDIT_VIEWER_FRONTEND_DIST=SP_COCKPIT_FRONTEND_DIST"
    "INDEXING_DB_PATH=SP_COCKPIT_INDEXING_DB_PATH"
)

renamed=0
if [ -f "$ENV_FILE" ]; then
    # Detect whether any old key exists
    needs_rewrite=0
    for pair in "${ENV_MAP[@]}"; do
        old="${pair%=*}"
        if grep -qE "^[[:space:]]*(export[[:space:]]+)?${old}=" "$ENV_FILE"; then
            needs_rewrite=1
            break
        fi
    done

    if [ "$needs_rewrite" -eq 1 ]; then
        if [ ! -f "$ENV_FILE.bak" ]; then
            cp "$ENV_FILE" "$ENV_FILE.bak"
            echo "[migrate] backed up .env → .env.bak"
        else
            echo "[migrate] .env.bak already exists, skipping backup"
        fi
        for pair in "${ENV_MAP[@]}"; do
            old="${pair%=*}"
            new="${pair#*=}"
            # Only rewrite at line start (or after `export `), and only the key portion
            sed -i -E "s|^([[:space:]]*(export[[:space:]]+)?)${old}=|\\1${new}=|" "$ENV_FILE"
        done
        renamed=1
        echo "[migrate] rewrote env keys in .env"
    else
        echo "[migrate] no legacy env keys found in .env (already migrated)"
    fi
else
    echo "[migrate] .env not present, skipping env rewrite"
fi

# Move data directory
if [ -d "$DIR/audit-viewer/data" ] && [ ! -d "$DIR/sp-cockpit/data" ]; then
    mkdir -p "$DIR/sp-cockpit"
    mv "$DIR/audit-viewer/data" "$DIR/sp-cockpit/data"
    echo "[migrate] moved audit-viewer/data → sp-cockpit/data"
elif [ -d "$DIR/sp-cockpit/data" ] && [ -d "$DIR/audit-viewer/data" ]; then
    echo "[migrate] both audit-viewer/data and sp-cockpit/data exist; leaving as-is (manual merge required)" >&2
elif [ -d "$DIR/sp-cockpit/data" ]; then
    echo "[migrate] sp-cockpit/data already exists, skipping move"
else
    echo "[migrate] no audit-viewer/data to move, skipping"
fi

# Summary
if [ "$renamed" -eq 1 ]; then
    echo "[migrate] DONE — .env keys rewritten. Backup at .env.bak"
else
    echo "[migrate] DONE — no env changes needed"
fi
