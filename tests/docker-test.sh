#!/usr/bin/env bash
set -euo pipefail

SP_URL=http://localhost:9000
ZOEKT_URL=http://localhost:6070

PASSED=0
FAILED=0

run_test() {
  local name="$1"
  shift
  if "$@"; then
    echo "PASS: $name"
    ((PASSED++))
  else
    echo "FAIL: $name"
    ((FAILED++))
  fi
}

echo "Waiting for Zoekt..."
curl --retry 15 --retry-delay 3 --retry-all-errors -sf "$ZOEKT_URL/" -o /dev/null

echo "Waiting for SourcePilot..."
curl --retry 15 --retry-delay 3 --retry-all-errors -sf "$SP_URL/api/health" -o /dev/null

# Test 1: Zoekt health
run_test "zoekt_health" curl -sf "$ZOEKT_URL/" -o /dev/null

# Test 2: SourcePilot health
run_test "sourcepilot_health" bash -c \
  "curl -sf '$SP_URL/api/health' | grep -q 'ok'"

# Test 3: SourcePilot search
run_test "sourcepilot_search" bash -c \
  "curl -s -X POST -H 'content-type: application/json' \
    -d '{\"query\":\"Binder\",\"top_k\":5}' \
    '$SP_URL/api/search' | jq -e 'type == \"array\" and length > 0' > /dev/null"

# Test 4: SourcePilot search_symbol
run_test "sourcepilot_search_symbol" bash -c \
  "curl -s -X POST -H 'content-type: application/json' \
    -d '{\"symbol\":\"Activity\",\"top_k\":3}' \
    '$SP_URL/api/search_symbol' | jq -e 'type == \"array\" and length > 0' > /dev/null"

echo ""
echo "PASSED=$PASSED FAILED=$FAILED"

if [[ "$FAILED" -eq 0 ]]; then
  exit 0
else
  exit 1
fi
