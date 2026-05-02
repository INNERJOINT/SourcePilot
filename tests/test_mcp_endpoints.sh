#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  AOSP Code Search MCP Server endpoint test cases
#
#  This script demonstrates how to call the MCP interface
#  directly via curl in Streamable HTTP mode.
#  Tests cover the three core capabilities exposed by MCP:
#  1. search_file
#  2. search_symbol
#  3. search_code
# ──────────────────────────────────────────────────────

# Server configuration
MCP_URL="http://localhost:8888/mcp"
TMP_DIR=$(mktemp -d)
SSE_OUTPUT="$TMP_DIR/sse_output.txt"

echo "=== AOSP Code Search MCP Server Test Cases ==="
echo "Make sure the server is started with:"
echo "  ./run_mcp.sh --transport streamable-http --port 8888"
echo "--------------------------------------------------------"

# 1. Establish SSE connection and obtain Session ID
echo ">>> [Handshake] Establishing SSE connection..."
curl -s -N -H "Accept: text/event-stream" "$MCP_URL" > "$SSE_OUTPUT" &
SSE_PID=$!

# Wait for connection to be established and get the session ID
sleep 2
SESSION_ID=$(grep -oP "(?<=mcp-session-id: ).*" "$SSE_OUTPUT" | head -1 | tr -d '\r')

if [ -z "$SESSION_ID" ]; then
    echo "❌ Error: Could not obtain Session ID. Check that the MCP service is running."
    kill $SSE_PID 2>/dev/null
    rm -r "$TMP_DIR"
    exit 1
fi
echo "✅ Session ID obtained: $SESSION_ID"
echo "--------------------------------------------------------"

# Helper function to send a JSON-RPC request
send_mcp_request() {
    local method_name=$1
    local id=$2
    local params_json=$3
    local desc=$4

    echo ">>> [Test case $id] Testing capability: $method_name ($desc)"

    # Build request body (CallToolRequest)
    local request_body=$(cat <<EOF
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

    # Clear previous SSE output
    > "$SSE_OUTPUT"

    # Send POST request
    curl -s -X POST "$MCP_URL" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json" \
        -H "mcp-session-id: $SESSION_ID" \
        -d "$request_body"

    # Wait for server to push response via SSE
    sleep 2

    echo "Server response (from SSE stream):"
    # Extract JSON-RPC response body and format it
    grep -oP "(?<=data: ).*" "$SSE_OUTPUT" | jq .
    echo "--------------------------------------------------------"
}

# 2. Test case 1: search_file
# Scenario: find "device_vendor_v1.xml" files containing "product" keyword
send_mcp_request "search_file" 1 '{"path": "device_vendor_v1.xml", "query": "product", "top_k": 3}' "file name + keyword search"

# 3. Test case 2: search_symbol
# Scenario: find the definition of "startBootstrapServices" method in AOSP
send_mcp_request "search_symbol" 2 '{"symbol": "startBootstrapServices", "top_k": 3}' "exact function/class definition search"

# 4. Test case 3: search_code
# Scenario: full-text keyword search in a specific repo (frameworks/base)
send_mcp_request "search_code" 3 '{"query": "ActivityManagerService init", "repo": "frameworks/base", "top_k": 3}' "full-text search within specific repo"

# Cleanup
echo ">>> Tests complete, cleaning up resources..."
kill $SSE_PID 2>/dev/null
rm -r "$TMP_DIR"
echo "✅ Test run complete."
