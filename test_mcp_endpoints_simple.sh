#!/bin/bash
# 简单的 curl 测试脚本，不依赖 jq

MCP_URL="http://localhost:8888/mcp"
TMP_DIR=$(mktemp -d)
SSE_OUTPUT="$TMP_DIR/sse_output.txt"

echo "=== AOSP Code Search MCP Server 测试用例 ==="
echo "启动 SSE 连接..."
curl -s -v -N -H "Accept: text/event-stream" "$MCP_URL" > "$SSE_OUTPUT" 2>&1 &
SSE_PID=$!

sleep 2
# 提取 mcp-session-id，兼容不同的 curl 输出格式
SESSION_ID=$(grep -i "mcp-session-id:" "$SSE_OUTPUT" | head -1 | awk '{print $3}' | tr -d '\r')

if [ -z "$SESSION_ID" ]; then
    echo "❌ 获取 Session ID 失败"
    cat "$SSE_OUTPUT"
    kill $SSE_PID 2>/dev/null
    rm -r "$TMP_DIR"
    exit 1
fi

echo "✅ Session ID: $SESSION_ID"
echo ""

# 发起初始化请求
echo ">>> [握手] 发送 initialize 请求..."
> "$SSE_OUTPUT"
curl -s -X POST "$MCP_URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "mcp-session-id: $SESSION_ID" \
    -d '{
        "jsonrpc": "2.0",
        "id": "init_1",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "curl-test", "version": "1.0.0"}
        }
    }'
sleep 1
cat "$SSE_OUTPUT" | grep -o '{.*}' | sed 's/^/  响应: /'
echo ""

# 1. search_file
echo ">>> [能力 1: search_file] 搜索 seewo_t1.xml 中包含 product 的内容"
> "$SSE_OUTPUT"
curl -s -X POST "$MCP_URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "mcp-session-id: $SESSION_ID" \
    -d '{
        "jsonrpc": "2.0",
        "id": "req_1",
        "method": "tools/call",
        "params": {
            "name": "search_file",
            "arguments": {"path": "seewo_t1.xml", "query": "product", "top_k": 1}
        }
    }'
sleep 1
cat "$SSE_OUTPUT" | grep -o '{.*}' | sed 's/^/  响应: /'
echo ""

# 2. search_symbol
echo ">>> [能力 2: search_symbol] 查找 startBootstrapServices 的定义"
> "$SSE_OUTPUT"
curl -s -X POST "$MCP_URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "mcp-session-id: $SESSION_ID" \
    -d '{
        "jsonrpc": "2.0",
        "id": "req_2",
        "method": "tools/call",
        "params": {
            "name": "search_symbol",
            "arguments": {"symbol": "startBootstrapServices", "top_k": 1}
        }
    }'
sleep 1
cat "$SSE_OUTPUT" | grep -o '{.*}' | sed 's/^/  响应: /'
echo ""

# 3. search_code
echo ">>> [能力 3: search_code] 在 frameworks/base 中搜索 ActivityManagerService"
> "$SSE_OUTPUT"
curl -s -X POST "$MCP_URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "mcp-session-id: $SESSION_ID" \
    -d '{
        "jsonrpc": "2.0",
        "id": "req_3",
        "method": "tools/call",
        "params": {
            "name": "search_code",
            "arguments": {"query": "ActivityManagerService", "repo": "frameworks/base", "top_k": 1}
        }
    }'
sleep 1
cat "$SSE_OUTPUT" | grep -o '{.*}' | sed 's/^/  响应: /'
echo ""

kill $SSE_PID 2>/dev/null
rm -r "$TMP_DIR"
