#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  AOSP Code Search MCP Server 接口测试用例
#
#  这个脚本演示了如何使用 curl 直接请求 Streamable HTTP
#  模式下的 MCP 接口。测试覆盖了 MCP 暴露的三个核心能力：
#  1. search_file
#  2. search_symbol
#  3. search_code
# ──────────────────────────────────────────────────────

# 服务器配置
MCP_URL="http://localhost:8888/mcp"
TMP_DIR=$(mktemp -d)
SSE_OUTPUT="$TMP_DIR/sse_output.txt"

echo "=== AOSP Code Search MCP Server 测试用例 ==="
echo "确保服务器已使用以下命令启动："
echo "  ./run_mcp.sh --transport streamable-http --port 8888"
echo "--------------------------------------------------------"

# 1. 建立 SSE 连接并获取 Session ID
echo ">>> [握手阶段] 建立 SSE 连接..."
curl -s -N -H "Accept: text/event-stream" "$MCP_URL" > "$SSE_OUTPUT" &
SSE_PID=$!

# 等待连接建立并获取 session ID
sleep 2
SESSION_ID=$(grep -oP "(?<=mcp-session-id: ).*" "$SSE_OUTPUT" | head -1 | tr -d '\r')

if [ -z "$SESSION_ID" ]; then
    echo "❌ 错误: 无法获取 Session ID，请检查 MCP 服务是否正常运行。"
    kill $SSE_PID 2>/dev/null
    rm -r "$TMP_DIR"
    exit 1
fi
echo "✅ 成功获取 Session ID: $SESSION_ID"
echo "--------------------------------------------------------"

# 定义一个发送 JSON-RPC 请求的辅助函数
send_mcp_request() {
    local method_name=$1
    local id=$2
    local params_json=$3
    local desc=$4

    echo ">>> [测试用例 $id] 测试能力: $method_name ($desc)"
    
    # 构建请求体 (CallToolRequest)
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

    echo "发送请求:"
    echo "$request_body" | jq .

    # 清空之前的 SSE 输出
    > "$SSE_OUTPUT"

    # 发送 POST 请求
    curl -s -X POST "$MCP_URL" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json" \
        -H "mcp-session-id: $SESSION_ID" \
        -d "$request_body"

    # 等待服务器通过 SSE 推送响应
    sleep 2
    
    echo "服务器响应 (从 SSE 流获取):"
    # 提取 JSON-RPC 响应体并格式化
    grep -oP "(?<=data: ).*" "$SSE_OUTPUT" | jq .
    echo "--------------------------------------------------------"
}

# 2. 测试用例 1: search_file
# 场景: 查找包含 "product" 关键字的 "seewo_t1.xml" 文件 (还原你的例子)
send_mcp_request "search_file" 1 '{"path": "seewo_t1.xml", "query": "product", "top_k": 3}' "文件名 + 关键字联合搜索"

# 3. 测试用例 2: search_symbol
# 场景: 查找 AOSP 中 "startBootstrapServices" 方法的定义
send_mcp_request "search_symbol" 2 '{"symbol": "startBootstrapServices", "top_k": 3}' "精确查找函数/类定义"

# 4. 测试用例 3: search_code
# 场景: 在特定仓库 (frameworks/base) 中进行全文关键字搜索
send_mcp_request "search_code" 3 '{"query": "ActivityManagerService init", "repo": "frameworks/base", "top_k": 3}' "特定仓库下的全文搜索"

# 清理
echo ">>> 测试完成，清理资源..."
kill $SSE_PID 2>/dev/null
rm -r "$TMP_DIR"
echo "✅ 测试结束。"
