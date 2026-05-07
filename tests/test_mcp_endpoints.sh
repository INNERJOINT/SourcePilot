#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  AOSP Code Search MCP Server endpoint test cases
#
#  This script exercises the MCP Streamable HTTP transport
#  via curl. It performs a JSON-RPC initialize handshake to
#  obtain Mcp-Session-Id, then invokes the three core tools:
#  1. search_file
#  2. search_symbol
#  3. search_code
# ──────────────────────────────────────────────────────

set -uo pipefail

# Load .env from repo root (only sets unset vars)
_ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/.env"
if [ -f "$_ENV_FILE" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    [[ -z "$line" || "$line" =~ ^[[:space:]]*$ ]] && continue
    line="${line#export }"
    key="${line%%=*}"
    val="${line#*=}"
    val="${val%\"}" ; val="${val#\"}" ; val="${val%\'}" ; val="${val#\'}"
    [ -z "${!key:-}" ] && export "$key=$val"
  done < "$_ENV_FILE"
fi

MCP_URL="${MCP_URL:-http://localhost:8888/mcp}"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

if [ -z "${MCP_AUTH_TOKEN:-}" ]; then
    echo "❌ Error: MCP_AUTH_TOKEN is not set. Export it or define it in .env."
    exit 1
fi
AUTH_HEADER="Authorization: Bearer $MCP_AUTH_TOKEN"

echo "=== AOSP Code Search MCP Server Test Cases ==="
echo "Endpoint: $MCP_URL"
echo "Make sure the server is started with:"
echo "  ./run_mcp.sh --transport streamable-http --port 8888"
echo "--------------------------------------------------------"

# 1. Initialize handshake → obtain Mcp-Session-Id from response headers
echo ">>> [Handshake] Sending initialize request..."
INIT_BODY='{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test_mcp_endpoints","version":"1.0"}}}'
INIT_HEADERS="$TMP_DIR/init_headers.txt"
INIT_BODY_OUT="$TMP_DIR/init_body.txt"

HTTP_CODE=$(curl -s -o "$INIT_BODY_OUT" -D "$INIT_HEADERS" -w "%{http_code}" \
    -X POST "$MCP_URL" \
    -H "$AUTH_HEADER" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d "$INIT_BODY")

if [ "$HTTP_CODE" != "200" ]; then
    echo "❌ Error: initialize failed with HTTP $HTTP_CODE"
    cat "$INIT_HEADERS" 2>/dev/null
    cat "$INIT_BODY_OUT" 2>/dev/null
    exit 1
fi

SESSION_ID=$(grep -i '^mcp-session-id:' "$INIT_HEADERS" | head -1 | cut -d: -f2- | tr -d ' \r\n')
if [ -z "$SESSION_ID" ]; then
    echo "❌ Error: Could not obtain Mcp-Session-Id from initialize response."
    cat "$INIT_HEADERS"
    exit 1
fi
echo "✅ Session ID obtained: $SESSION_ID"

# Send the required notifications/initialized notification (no response expected)
NOTIFY_BODY='{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'
curl -s -o /dev/null -X POST "$MCP_URL" \
    -H "$AUTH_HEADER" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "mcp-session-id: $SESSION_ID" \
    -d "$NOTIFY_BODY"
echo "--------------------------------------------------------"

# Helper: send a tools/call JSON-RPC request and print the result
send_mcp_request() {
    local method_name=$1
    local id=$2
    local params_json=$3
    local desc=$4

    echo ">>> [Test case $id] Testing capability: $method_name ($desc)"

    local request_body
    request_body=$(cat <<EOF
{
    "jsonrpc": "2.0",
    "id": $id,
    "method": "tools/call",
    "params": {
        "name": "$method_name",
        "arguments": $params_json
    }
}
EOF
)

    echo "Sending request:"
    echo "$request_body" | jq .

    local response_file="$TMP_DIR/resp_${id}.txt"
    local code
    code=$(curl -s -o "$response_file" -w "%{http_code}" \
        -X POST "$MCP_URL" \
        -H "$AUTH_HEADER" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -H "mcp-session-id: $SESSION_ID" \
        -d "$request_body")

    echo "HTTP $code"
    echo "Server response:"
    # Streamable HTTP returns either application/json or text/event-stream.
    # Extract JSON-RPC payload from SSE "data: ..." lines if present, else dump as JSON.
    local payload="$TMP_DIR/payload_${id}.json"
    if grep -q '^data:' "$response_file"; then
        grep '^data:' "$response_file" | sed 's/^data: //' | tee "$payload" | jq .
    else
        cp "$response_file" "$payload"
        jq . "$payload" 2>/dev/null || cat "$payload"
    fi
    echo "--------------------------------------------------------"

    if [ "$code" != "200" ]; then
        return 1
    fi
    # Treat tool-level errors (isError=true or top-level error) as test failures
    if jq -e '.error' "$payload" >/dev/null 2>&1; then
        return 1
    fi
    if jq -e '.result.isError == true' "$payload" >/dev/null 2>&1; then
        return 1
    fi
}

EXIT_CODE=0

# Test 1: search_file
send_mcp_request "search_file" 1 \
    '{"inp": {"path": "device_vendor_v1.xml", "query": "product", "top_k": 3, "project": "ace"}}' \
    "file name + keyword search" || EXIT_CODE=1

# Test 2: search_symbol
send_mcp_request "search_symbol" 2 \
    '{"inp": {"symbol": "startBootstrapServices", "top_k": 3, "project": "ace"}}' \
    "exact function/class definition search" || EXIT_CODE=1

# Test 3: search_code
send_mcp_request "search_code" 3 \
    '{"inp": {"query": "ActivityManagerService init", "repo": "frameworks/base", "top_k": 3, "project": "ace"}}' \
    "full-text search within specific repo" || EXIT_CODE=1

# Best-effort session shutdown (DELETE may be unsupported by some transports)
curl -s -o /dev/null -X DELETE "$MCP_URL" \
    -H "$AUTH_HEADER" \
    -H "mcp-session-id: $SESSION_ID" || true

if [ "$EXIT_CODE" -eq 0 ]; then
    echo "✅ Test run complete."
else
    echo "❌ One or more tool calls failed."
fi
exit "$EXIT_CODE"
