#!/usr/bin/env bash
# _indexing_lib.sh — shell helper functions for indexing job lifecycle
#
# Source this file in indexing scripts:
#   source "$(dirname "$0")/_indexing_lib.sh"
#
# Functions:
#   start_indexing_job  repo_path backend   — registers job, sets JOB_ID + LOG_PATH, arms trap
#   finish_indexing_job status [exit_code]  — reports completion, disarms trap

# Guard against double-sourcing
if [[ -n "${_INDEXING_LIB_LOADED:-}" ]]; then
    return 0
fi
_INDEXING_LIB_LOADED=1

# Directory containing this file (works regardless of CWD)
_INDEXING_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Project root (one level up from scripts/)
_INDEXING_PROJECT_ROOT="$(cd "$_INDEXING_LIB_DIR/.." && pwd)"

# Python interpreter (honour virtualenv if active, otherwise fall back to system python3)
_INDEXING_PYTHON="${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/python3}"
_INDEXING_PYTHON="${_INDEXING_PYTHON:-python3}"

# API URL — can be overridden via env
INDEXING_API_URL="${INDEXING_API_URL:-http://localhost:9100}"

# ---------------------------------------------------------------------------
# start_indexing_job repo_path backend
#   Exports JOB_ID and LOG_PATH; arms EXIT trap.
# ---------------------------------------------------------------------------
start_indexing_job() {
    local repo_path="$1"
    local backend="$2"

    # Build a deterministic log path
    local safe_repo
    safe_repo="$(echo "$repo_path" | tr '/' '_')"
    LOG_PATH="$_INDEXING_PROJECT_ROOT/.omc/indexing-logs/${backend}-${safe_repo}-$(date +%s).log"
    mkdir -p "$(dirname "$LOG_PATH")"

    # Call CLI — capture stdout to extract JOB_ID=<id>
    local cli_output
    cli_output=$(
        cd "$_INDEXING_PROJECT_ROOT" && \
        INDEXING_API_URL="$INDEXING_API_URL" \
        "$_INDEXING_PYTHON" -m audit_viewer.indexing_cli \
            start \
            --repo-path "$repo_path" \
            --backend "$backend" \
            --log-path "$LOG_PATH" \
            2>&1 | tee -a "$LOG_PATH" || true
    )
    JOB_ID=$(echo "$cli_output" | grep 'JOB_ID=' | tail -1 | cut -d= -f2)
    export JOB_ID LOG_PATH

    if [[ -z "$JOB_ID" ]]; then
        echo "[indexing-lib] WARN: could not obtain JOB_ID — job tracking disabled" >&2
    else
        echo "[indexing-lib] Started job $JOB_ID (backend=$backend, repo=$repo_path)" >&2
    fi

    # Arm EXIT trap — fires on abnormal exit (set -e, kill, etc.)
    # The trap disarms itself via finish_indexing_job which clears it.
    trap '_indexing_exit_trap $?' EXIT
}

# Internal trap handler
_indexing_exit_trap() {
    local exit_code="${1:-1}"
    finish_indexing_job fail "$exit_code"
}

# ---------------------------------------------------------------------------
# finish_indexing_job status [exit_code]
#   Disarms EXIT trap, calls CLI finish.
# ---------------------------------------------------------------------------
finish_indexing_job() {
    local status="${1:-fail}"
    local exit_code="${2:-0}"

    # Disarm trap first so we don't recurse
    trap - EXIT

    if [[ -z "${JOB_ID:-}" ]]; then
        echo "[indexing-lib] WARN: JOB_ID not set — skipping finish" >&2
        return 0
    fi

    echo "[indexing-lib] Finishing job $JOB_ID status=$status exit_code=$exit_code" >&2

    cd "$_INDEXING_PROJECT_ROOT" && \
    INDEXING_API_URL="$INDEXING_API_URL" \
    "$_INDEXING_PYTHON" -m audit_viewer.indexing_cli \
        finish \
        --job-id "$JOB_ID" \
        --status "$status" \
        --exit-code "$exit_code" || true
}
