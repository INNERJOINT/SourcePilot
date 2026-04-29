#!/usr/bin/env bash
# verify.sh — unified verification for structural audit and indexer containers
#
# Usage:
#   scripts/verify.sh structural-audit
#   scripts/verify.sh indexer-containers
#
# Subcommands:
#   structural-audit     — Structural audit event end-to-end verification
#   indexer-containers   — Verify dense/structural indexer definitions in docker-compose.yml
set -euo pipefail
source "$(dirname "$0")/../share/_common.sh"
_common_parse_help "$@"

# ─── structural-audit ──────────────────────────────────────────────────────────

_run_structural_audit() {
  local SOURCEPILOT_URL="${SOURCEPILOT_URL:-http://localhost:9000}"
  local SP_COCKPIT_URL="${SP_COCKPIT_URL:-http://localhost:9100}"
  local AUDIT_DB="${AUDIT_DB:-/opt/aosp/aosp_project2/Dify/sp-cockpit/data/audit.db}"

  info "Checking sp-cockpit health..."
  if ! curl -sf "${SP_COCKPIT_URL}/api/health" > /dev/null 2>&1; then
    log ERROR "sp-cockpit not responding (${SP_COCKPIT_URL}/api/health)"
    echo ""
    echo "Please start sp-cockpit first:"
    echo "  cd /opt/aosp/aosp_project2/Dify && bash scripts/run_all.sh"
    echo "  # Or start independently: cd sp-cockpit && uvicorn main:app --port 9100"
    return 1
  fi
  info "sp-cockpit responding normally"

  info "Checking SourcePilot health..."
  if ! curl -sf "${SOURCEPILOT_URL}/health" > /dev/null 2>&1; then
    log ERROR "SourcePilot not responding (${SOURCEPILOT_URL}/health)"
    return 1
  fi
  info "SourcePilot responding normally"

  info "Checking STRUCTURAL_ENABLED environment variable..."
  local STRUCTURAL_ENABLED_STATUS
  STRUCTURAL_ENABLED_STATUS=$(curl -sf "${SOURCEPILOT_URL}/health" | grep -o '"structural":[^,}]*' || echo "unknown")
  info "structural status: ${STRUCTURAL_ENABLED_STATUS}"

  info "Checking audit.db..."
  if [ ! -f "${AUDIT_DB}" ]; then
    log ERROR "audit.db does not exist: ${AUDIT_DB}"
    echo "sp-cockpit has not yet ingested logs, please retry after 30s"
    return 1
  fi
  info "audit.db exists"

  # ─── Send test queries ─────────────────────────────────────────────────────────

  info "Sending 3 test queries..."

  local TRACE_PREFIX="trace-structural-verify-$$"
  local i TRACE_ID QUERY HTTP_STATUS

  for i in 1 2 3; do
    TRACE_ID="${TRACE_PREFIX}-${i}"
    QUERY="startActivity intent android"
    case $i in
      2) QUERY="BroadcastReceiver register filter" ;;
      3) QUERY="WindowManagerService token window" ;;
    esac

    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
      -X POST "${SOURCEPILOT_URL}/api/search" \
      -H "Content-Type: application/json" \
      -H "X-Trace-Id: ${TRACE_ID}" \
      -d "{\"query\": \"${QUERY}\", \"top_k\": 5}" \
      2> /dev/null || echo "000")

    if [ "${HTTP_STATUS}" = "200" ]; then
      info "Query ${i} succeeded (trace: ${TRACE_ID})"
    else
      log ERROR "Query ${i} failed (HTTP ${HTTP_STATUS}, trace: ${TRACE_ID})"
    fi
  done

  # ─── Wait for ingestion ─────────────────────────────────────────────────────────────

  info "Waiting for sp-cockpit to ingest logs (3s)..."
  sleep 3

  # ─── Verify structural_search events ──────────────────────────────────────────────

  info "Querying structural_search events in audit.db..."

  local STRUCTURAL_COUNT
  STRUCTURAL_COUNT=$(sqlite3 "${AUDIT_DB}" \
    "SELECT count(*) FROM events WHERE json_extract(data, '\$.stage') = 'structural_search'" \
    2> /dev/null || echo "0")

  echo "structural_search event count: ${STRUCTURAL_COUNT}"

  if [ "${STRUCTURAL_COUNT}" -gt 0 ]; then
    info "structural_search events recorded (total: ${STRUCTURAL_COUNT})"
  else
    log ERROR "No structural_search events found (is STRUCTURAL_ENABLED set to true?)"
    echo ""
    echo "Debug steps:"
    echo "  1. Confirm STRUCTURAL_ENABLED=true is set"
    echo "  2. Confirm Neo4j is accessible and structural index has been built"
    echo "  3. Check audit.log: tail -50 /opt/aosp/aosp_project2/Dify/audit.log | grep structural_search"
  fi

  # ─── Latency comparison report ────────────────────────────────────────────────────────

  echo ""
  info "Lane latency comparison (last 30 entries, by duration_ms descending):"
  echo "────────────────────────────────────────────────────"
  sqlite3 "${AUDIT_DB}" \
    "SELECT json_extract(data, '\$.stage') AS stage,
                printf('%.1f', json_extract(data, '\$.duration_ms')) AS ms
         FROM events
         WHERE json_extract(data, '\$.stage') IN ('zoekt_search','dense_search','structural_search')
         ORDER BY CAST(json_extract(data, '\$.duration_ms') AS REAL) DESC
         LIMIT 30" \
    2> /dev/null | column -t -s '|' || echo "(no data)"
  echo "────────────────────────────────────────────────────"

  # ─── Summary ────────────────────────────────────────────────────────────────

  echo ""
  if [ "${STRUCTURAL_COUNT}" -gt 0 ]; then
    info "Structural audit verification passed: structural_search events end-to-end OK"
    return 0
  else
    log ERROR "Structural audit verification failed: no structural_search events found"
    return 1
  fi
}

# ─── indexer-containers ──────────────────────────────────────────────────────

_run_indexer_containers() {
  local DIR
  DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
  local COMPOSE="$DIR/deploy/docker-compose.yml"
  local AOSP_SOURCE_ROOT="${AOSP_SOURCE_ROOT:-/opt/aosp/aosp_project}"
  export AOSP_SOURCE_ROOT

  local fail=0

  _check() {
    local label="$1"
    shift
    echo "==> $label"
    if "$@"; then
      echo "    OK"
    else
      echo "    FAIL ($*)" >&2
      fail=1
    fi
  }

  if ! command -v docker > /dev/null 2>&1; then
    echo "docker not installed; skipping verification."
    return 0
  fi

  _check "deploy compose config (profile=indexer)" \
    docker compose -f "$COMPOSE" --profile indexer config -q
  _check "deploy compose config (default profile — should not contain dense-indexer/structural-indexer)" \
    bash -c "svc=\$(docker compose -f '$COMPOSE' config --services); echo \"\$svc\" | grep -vq '^dense-indexer\$' && echo \"\$svc\" | grep -vq '^structural-indexer\$'"
  _check "deploy compose project name = sourcepilot" \
    bash -c "docker compose -f '$COMPOSE' config | grep -E '^name:' | grep -q 'sourcepilot'"
  _check "root shim resolves to deploy compose" \
    docker compose -f "$DIR/docker-compose.yml" config -q

  if [[ "${INDEXER_RUN_HELP:-0}" = "1" ]]; then
    _check "dense-indexer --help" \
      docker compose -f "$COMPOSE" --profile indexer run --rm dense-indexer --help
    _check "structural-indexer --help" \
      docker compose -f "$COMPOSE" --profile indexer run --rm structural-indexer --help
  fi

  return "$fail"
}

# ─── dispatch ────────────────────────────────────────────────────────────────

case "${1:-}" in
  structural-audit)
    shift
    _run_structural_audit "$@"
    ;;
  indexer-containers)
    shift
    _run_indexer_containers "$@"
    ;;
  *) die "Usage: verify.sh <structural-audit|indexer-containers>" ;;
esac
