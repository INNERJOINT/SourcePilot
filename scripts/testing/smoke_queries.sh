#!/usr/bin/env bash
# scripts/smoke_queries.sh — SourcePilot manual smoke test
#
# Usage:
#   scripts/run_all.sh            # Start SourcePilot/zoekt/Qdrant/sp-cockpit first
#   bash scripts/smoke_queries.sh
#
# Prerequisites:
#   - DENSE_ENABLED=true (must be set when SourcePilot starts)
#   - Qdrant running, frameworks/base vector index complete
#   - sp-cockpit running (port 9100), audit.db being populated
#   - Audit review URL: http://localhost:9100  (filter by trace_id for manual review)
#
# Dependencies: bash + curl + jq + sqlite3 + (uuidgen or openssl) + GNU date (Linux)
# Endpoint: SourcePilot HTTP API (default http://localhost:9000)
# Exit code: 0 all PASS and audit passed / 1 any FAIL or audit failed / 2 pre-flight check failed

set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/../share/_common.sh"
_common_parse_help "$@"

SOURCEPILOT_URL="${SOURCEPILOT_URL:-http://localhost:9000}"
TIMEOUT="${TIMEOUT:-15}"
AUDIT_DB="${AUDIT_DB:-${SP_COCKPIT_AUDIT_DB_PATH:-sp-cockpit/data/audit.db}}"

# *_BIN injection points — override to swap in test stubs without PATH tricks
CURL_BIN="${CURL_BIN:-curl}"
JQ_BIN="${JQ_BIN:-jq}"
SQLITE3_BIN="${SQLITE3_BIN:-sqlite3}"
UUIDGEN_BIN="${UUIDGEN_BIN:-uuidgen}"
OPENSSL_BIN="${OPENSSL_BIN:-openssl}"

# Multi-project deployments require explicit project on every call.
AOSP_PROJECT="${AOSP_PROJECT:-aosp_project}"

# ─── gen_trace_id utility function ────────────────────────
gen_trace_id() {
  if command -v uuidgen > /dev/null 2>&1; then
    "$UUIDGEN_BIN" | tr '[:upper:]' '[:lower:]' | tr -d '-'
  else
    "$OPENSSL_BIN" rand -hex 16
  fi
}

# ─── counters ────────────────────────────────────────
PASSED=0
FAILED=0
SKIPPED=0

# ─── associative arrays: store trace_id for each test case ───────────────
declare -A TRACE_IDS

# ─── common runner ────────────────────────────────────
# run_case <name> <path> <json> <optional:yes|no> <shape:list|dict>
run_case() {
  local name="$1" path="$2" json="$3" optional="$4" shape="$5"

  local trace_id
  trace_id=$(gen_trace_id)
  TRACE_IDS["$name"]="$trace_id"

  local start http_code dur count status parse_ok=0 has_error=1

  start=$(date +%s%3N)
  http_code=$("$CURL_BIN" -s --max-time "$TIMEOUT" \
    -o "$RESP_FILE" -w "%{http_code}" \
    -X POST -H "content-type: application/json" \
    -H "X-Trace-Id: $trace_id" \
    -d "$json" \
    "$SOURCEPILOT_URL$path" 2> /dev/null || echo "000")
  dur=$(($(date +%s%3N) - start))

  if "$JQ_BIN" -e '.' "$RESP_FILE" > /dev/null 2>&1; then
    parse_ok=1
  fi

  if [[ "$shape" == "list" ]]; then
    count=$("$JQ_BIN" 'length' "$RESP_FILE" 2> /dev/null || echo "?")
  else
    count=1
  fi

  if "$JQ_BIN" -e 'type == "object" and has("error")' "$RESP_FILE" > /dev/null 2>&1; then
    has_error=0
  fi

  if [[ "$http_code" == "200" && $parse_ok -eq 1 && $has_error -ne 0 ]]; then
    status="PASS"
    PASSED=$((PASSED + 1))
  elif [[ "$optional" == "yes" ]]; then
    status="SKIP"
    SKIPPED=$((SKIPPED + 1))
  else
    status="FAIL"
    FAILED=$((FAILED + 1))
  fi

  printf '[%s] %-20s http=%s ms=%s count=%s trace=%s\n' \
    "$status" "$name" "$http_code" "$dur" "$count" "$trace_id"
}

main() {
  RESP_FILE="$(mktemp -t smoke_resp.XXXXXX.json)"
  trap 'rm -f "$RESP_FILE"' EXIT

  # ─── Pre-flight checks ────────────────────────────────────────
  for tool in curl jq sqlite3; do
    if ! command -v "$tool" > /dev/null 2>&1; then
      echo "ERROR: requires $tool, please install first" >&2
      exit 2
    fi
  done

  if ! command -v uuidgen > /dev/null 2>&1 && ! command -v openssl > /dev/null 2>&1; then
    echo "ERROR: requires uuidgen or openssl, please install either one" >&2
    exit 2
  fi

  if [[ ! -f "$AUDIT_DB" ]]; then
    echo "ERROR: audit.db does not exist: $AUDIT_DB" >&2
    echo "       please run sp-cockpit first to create and populate audit.db" >&2
    exit 2
  fi

  if ! "$CURL_BIN" -fsS --max-time "$TIMEOUT" "$SOURCEPILOT_URL/api/health" > /dev/null 2>&1; then
    echo "ERROR: SourcePilot health check failed (GET $SOURCEPILOT_URL/api/health)" >&2
    echo "       please run scripts/run_all.sh to start services first" >&2
    exit 2
  fi

  # ─── dense-enabled probe ──────────────────────────────
  probe_tid=$(gen_trace_id)
  "$CURL_BIN" -s --max-time "$TIMEOUT" \
    -o /dev/null \
    -X POST -H "content-type: application/json" \
    -H "X-Trace-Id: $probe_tid" \
    -d '{"query":"binder driver permission check probe","top_k":3}' \
    "$SOURCEPILOT_URL/api/search" 2> /dev/null || true
  probe_count=0
  for _ in 1 2 3; do
    sleep 1
    probe_count=$("$SQLITE3_BIN" "$AUDIT_DB" "SELECT count(*) FROM events WHERE stage='dense_search' AND trace_id='$probe_tid'" 2> /dev/null || echo "0")
    [[ "$probe_count" -gt 0 ]] && break
  done
  if [[ "$probe_count" -eq 0 ]]; then
    echo "ERROR: dense_search stage not seen after 3s. Set DENSE_ENABLED=true, ensure Qdrant is running with frameworks/base indexed, and restart SourcePilot." >&2
    exit 2
  fi

  echo "=== SourcePilot smoke @ $SOURCEPILOT_URL ==="

  run_case zoekt_keyword /api/search "{\"query\":\"binder_open\",\"top_k\":5,\"project\":\"$AOSP_PROJECT\"}" no list
  run_case nl_inscope_dense /api/search "{\"query\":\"binder driver permission check mechanism\",\"top_k\":5,\"project\":\"$AOSP_PROJECT\"}" no list
  run_case nl_outscope_dense /api/search "{\"query\":\"Launcher3 home screen layout loading flow\",\"top_k\":5,\"project\":\"$AOSP_PROJECT\"}" no list
  run_case symbol /api/search_symbol "{\"symbol\":\"startBootstrapServices\",\"top_k\":3,\"project\":\"$AOSP_PROJECT\"}" no list
  run_case file /api/search_file "{\"path\":\"AndroidManifest.xml\",\"top_k\":3,\"project\":\"$AOSP_PROJECT\"}" no list
  run_case regex /api/search_regex "{\"pattern\":\"binder_[a-z_]+\",\"top_k\":3,\"project\":\"$AOSP_PROJECT\"}" no list
  run_case list_repos /api/list_repos "{\"query\":\"\",\"top_k\":5,\"project\":\"$AOSP_PROJECT\"}" no list
  run_case get_file /api/get_file_content "{\"repo\":\"frameworks/base\",\"filepath\":\"core/java/android/os/Binder.java\",\"start_line\":1,\"end_line\":40,\"project\":\"$AOSP_PROJECT\"}" yes dict

  echo "---"
  echo "PASSED=$PASSED FAILED=$FAILED SKIPPED=$SKIPPED"
  echo "(Note: count=0 is not a fail; PASS only checks HTTP 200 + parseable JSON)"

  echo "--- audit verification @ $AUDIT_DB ---"
  AUDIT_FAIL=0

  expected=${#TRACE_IDS[@]}
  ids_csv=$(printf "'%s'," "${TRACE_IDS[@]}" | sed 's/,$//')
  for _ in 1 2 3 4 5 6; do
    seen=$("$SQLITE3_BIN" "$AUDIT_DB" "SELECT count(DISTINCT trace_id) FROM events WHERE trace_id IN ($ids_csv)" 2> /dev/null || echo "0")
    [[ "$seen" -ge "$expected" ]] && break
    sleep 1
  done

  required_stages=(classify rewrite zoekt_search dense_search nl_parallel_search rrf_merge rerank
    search_symbol search_file search_regex list_repos get_file_content)
  have=$("$SQLITE3_BIN" "$AUDIT_DB" "SELECT DISTINCT stage FROM events WHERE trace_id IN ($ids_csv) AND stage IS NOT NULL" 2> /dev/null || true)
  for s in "${required_stages[@]}"; do
    if ! grep -qx "$s" <<< "$have"; then
      echo "[FAIL] stage missing: $s" >&2
      AUDIT_FAIL=$((AUDIT_FAIL + 1))
    fi
  done

  in_tid="${TRACE_IDS[nl_inscope_dense]}"
  in_hits=$("$SQLITE3_BIN" "$AUDIT_DB" 'SELECT COALESCE(json_extract(payload_json,"$.stage_result.records_count"),0) FROM events WHERE trace_id='"'$in_tid'"' AND stage='"'dense_search'"' LIMIT 1' 2> /dev/null || echo "")
  if [[ -z "$in_hits" || "$in_hits" -le 0 ]]; then
    echo "[FAIL] in-scope dense records_count not >0 (got: '$in_hits')" >&2
    AUDIT_FAIL=$((AUDIT_FAIL + 1))
  fi

  out_tid="${TRACE_IDS[nl_outscope_dense]}"
  out_dense=$("$SQLITE3_BIN" "$AUDIT_DB" 'SELECT COALESCE(json_extract(payload_json,"$.stage_result.records_count"),0) FROM events WHERE trace_id='"'$out_tid'"' AND stage='"'dense_search'"' LIMIT 1' 2> /dev/null || echo "0")
  [[ "$out_dense" -ne 0 ]] && {
    echo "[FAIL] out-of-scope dense records_count expected 0 (got: '$out_dense')" >&2
    AUDIT_FAIL=$((AUDIT_FAIL + 1))
  }

  out_zoekt=$("$SQLITE3_BIN" "$AUDIT_DB" 'SELECT COALESCE(json_extract(payload_json,"$.stage_result.zoekt_routes_succeeded"),0) FROM events WHERE trace_id='"'$out_tid'"' AND stage='"'nl_parallel_search'"' LIMIT 1' 2> /dev/null || echo "0")
  [[ "$out_zoekt" -le 0 ]] && {
    echo "[FAIL] out-of-scope zoekt_routes_succeeded expected >0 (got: '$out_zoekt')" >&2
    AUDIT_FAIL=$((AUDIT_FAIL + 1))
  }

  echo "AUDIT_FAIL=$AUDIT_FAIL"
  echo "Audit review URL: http://localhost:9100  (filter by trace_id for manual review of rewrite/RRF/rerank)"
  for n in "${!TRACE_IDS[@]}"; do printf '  %-22s trace_id=%s\n' "$n" "${TRACE_IDS[$n]}"; done

  if ((FAILED == 0 && AUDIT_FAIL == 0)); then
    exit 0
  else
    exit 1
  fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
