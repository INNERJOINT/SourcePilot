#!/usr/bin/env bash
# scripts/test_dense.sh — Test whether dense search is triggered
#
# Usage:
#   DENSE_ENABLED=true scripts/run_sourcepilot.sh   # Start first (requires Qdrant + Embedding service)
#   bash scripts/test_dense.sh
#
# Prerequisites:
#   - SourcePilot started with DENSE_ENABLED=true
#   - Qdrant running (default localhost:6333)
#   - Embedding service running (default localhost:8080)
#   - frameworks/base vector indexing completed
#
# Dependencies: curl + jq

set -euo pipefail

source "$(dirname "$0")/../share/_common.sh"
_common_parse_help "$@"

SOURCEPILOT_URL="${SOURCEPILOT_URL:-http://localhost:9000}"
TIMEOUT="${TIMEOUT:-15}"
AUDIT_LOG="${AUDIT_LOG:-audit.log}"

for tool in curl jq; do
  if ! command -v "$tool" > /dev/null 2>&1; then
    echo "ERROR: $tool is required" >&2
    exit 2
  fi
done

# ─── Health check ────────────────────────────────────────
if ! curl -fsS --max-time "$TIMEOUT" "$SOURCEPILOT_URL/api/health" > /dev/null 2>&1; then
  echo "ERROR: SourcePilot unreachable ($SOURCEPILOT_URL/api/health)" >&2
  exit 2
fi
echo "SourcePilot OK: $SOURCEPILOT_URL"

# ─── Generate trace_id ───────────────────────────────────
if command -v uuidgen > /dev/null 2>&1; then
  TRACE_ID=$(uuidgen | tr '[:upper:]' '[:lower:]' | tr -d '-')
else
  TRACE_ID=$(openssl rand -hex 16)
fi

# ─── Send NL query (only the NL path triggers dense) ────────
QUERY="binder driver permission verification mechanism"
echo ""
echo ">>> Sending NL query: \"$QUERY\""
echo "    trace_id: $TRACE_ID"
echo ""

RESP=$(mktemp -t dense_test.XXXXXX.json)
trap 'rm -f "$RESP"' EXIT

HTTP_CODE=$(curl -s --max-time "$TIMEOUT" \
  -o "$RESP" -w "%{http_code}" \
  -X POST -H "content-type: application/json" \
  -H "X-Trace-Id: $TRACE_ID" \
  -d "$(jq -nc --arg q "$QUERY" '{query: $q, top_k: 5}')" \
  "$SOURCEPILOT_URL/api/search" 2> /dev/null || echo "000")

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "FAIL: HTTP $HTTP_CODE" >&2
  cat "$RESP" 2> /dev/null
  exit 1
fi

RESULT_COUNT=$(jq 'length' "$RESP" 2> /dev/null || echo "?")
echo "HTTP 200 — returned $RESULT_COUNT results"

# ─── Check whether results contain dense source ──────────────────
DENSE_COUNT=$(jq '[.[] | select(.source == "dense")] | length' "$RESP" 2> /dev/null || echo "0")
ZOEKT_COUNT=$(jq '[.[] | select(.source != "dense")] | length' "$RESP" 2> /dev/null || echo "0")

echo ""
echo "Source breakdown:"
echo "  zoekt:  $ZOEKT_COUNT results"
echo "  dense:  $DENSE_COUNT results"

# ─── Verify dense_search stage from audit.log ────────────
echo ""
echo "--- audit.log verification ---"

if [[ ! -f "$AUDIT_LOG" ]]; then
  echo "WARN: $AUDIT_LOG does not exist, skipping audit verification"
  echo "      Set AUDIT_LOG to point to the actual path"
else
  sleep 1
  DENSE_STAGE=$(grep "$TRACE_ID" "$AUDIT_LOG" | grep '"dense_search"' | head -1)
  if [[ -n "$DENSE_STAGE" ]]; then
    records=$(echo "$DENSE_STAGE" | jq -r '.stage_result.records_count // 0' 2> /dev/null || echo "?")
    echo "[PASS] dense_search stage was triggered (records_count=$records)"
  else
    echo "[FAIL] dense_search stage not found in audit.log"
    echo "       Possible causes:"
    echo "       1. DENSE_ENABLED is not set to true"
    echo "       2. Query was not classified as NL intent by the classifier"
    echo "       3. Qdrant/Embedding service connection failed"
    exit 1
  fi

  # Show the full stage chain for this trace
  echo ""
  echo "Stage chain for this request:"
  grep "$TRACE_ID" "$AUDIT_LOG" | jq -r '"  " + .stage + " → " + (.stage_result // {} | tostring | .[0:80])' 2> /dev/null || true
fi

echo ""
if [[ "$DENSE_COUNT" -gt 0 ]]; then
  echo "PASS: dense search was triggered and returned results"
  exit 0
else
  echo "WARN: dense search may have been triggered but returned no matching results (collection may lack relevant data)"
  exit 0
fi
