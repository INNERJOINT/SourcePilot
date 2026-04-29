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

set -euo pipefail

# Directory containing this file (works regardless of CWD)
_INDEXING_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Project root (one level up from scripts/)
_INDEXING_PROJECT_ROOT="$(cd "$_INDEXING_LIB_DIR/../.." && pwd)"

# Python interpreter (honour virtualenv if active, otherwise fall back to system python3)
_INDEXING_PYTHON="${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/python3}"
_INDEXING_PYTHON="${_INDEXING_PYTHON:-python3}"

# API URL — can be overridden via env
INDEXING_API_URL="${INDEXING_API_URL:-http://localhost:9100}"

# ---------------------------------------------------------------------------
# start_indexing_job repo_path backend [project_name]
#   Exports JOB_ID and LOG_PATH; arms EXIT trap.
# ---------------------------------------------------------------------------
start_indexing_job() {
  local repo_path="$1"
  local backend="$2"
  local project_name="${3:-}"
  local project_args=()
  if [[ -n "$project_name" ]]; then
    project_args=(--project-name "$project_name")
  fi

  # Build a deterministic log path
  local safe_repo
  safe_repo="$(echo "$repo_path" | tr '/' '_')"
  LOG_PATH="$_INDEXING_PROJECT_ROOT/.omc/indexing-logs/${backend}-${safe_repo}-$(date +%s).log"
  mkdir -p "$(dirname "$LOG_PATH")"

  # Call CLI — capture stdout to extract JOB_ID=<id>
  local cli_output
  cli_output=$(
    cd "$_INDEXING_PROJECT_ROOT" &&
      INDEXING_API_URL="$INDEXING_API_URL" \
        "$_INDEXING_PYTHON" -m sp_cockpit.indexing_cli \
        start \
        --repo-path "$repo_path" \
        --backend "$backend" \
        --log-path "$LOG_PATH" \
        "${project_args[@]}" \
        2>&1 | tee -a "$LOG_PATH" || true
  )
  JOB_ID=$(echo "$cli_output" | grep 'JOB_ID=' | tail -1 | cut -d= -f2 || true)
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

  cd "$_INDEXING_PROJECT_ROOT" &&
    INDEXING_API_URL="$INDEXING_API_URL" \
      "$_INDEXING_PYTHON" -m sp_cockpit.indexing_cli \
      finish \
      --job-id "$JOB_ID" \
      --status "$status" \
      --exit-code "$exit_code" || true
}

# ---------------------------------------------------------------------------
# _get_project_config project_name
#   Reads _project_config.py output and sets NAME, REPO_PATH, INDEX_DIR,
#   ZOEKT_URL, SHARED_INDEX_DIR as local-scope variables in the caller.
#   Safe alternative to eval — parses key=value lines directly.
# ---------------------------------------------------------------------------
_INDEXING_PYHELPER="${_INDEXING_LIB_DIR}/_project_config.py"

_get_project_config() {
  local line key val
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    # Strip surrounding single quotes added by the Python helper
    val="${val#\'}"
    val="${val%\'}"
    case "$key" in
      NAME) NAME="$val" ;;
      REPO_PATH) REPO_PATH="$val" ;;
      INDEX_DIR) INDEX_DIR="$val" ;;
      ZOEKT_URL) ZOEKT_URL="$val" ;;
      SHARED_INDEX_DIR) SHARED_INDEX_DIR="$val" ;;
      *) echo "[indexing-lib] WARN: Unknown config key: $key" >&2 ;;
    esac
  done < <(python3 "$_INDEXING_PYHELPER" --project "$1")
}

# ---------------------------------------------------------------------------
# _wait_for_slot max_jobs
#   Block until background job count drops below max_jobs.
# ---------------------------------------------------------------------------
_wait_for_slot() {
  local max_jobs="$1"
  while true; do
    local running
    running=$(jobs -rp | wc -l)
    if [[ "$running" -lt "$max_jobs" ]]; then
      break
    fi
    wait -n 2> /dev/null || true
  done
}
