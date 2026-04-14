#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  AOSP Code Search MCP Server 启动脚本
#
#  支持两种传输模式：
#    ./run_mcp.sh                               # stdio 模式（默认，供 Claude Code / Cursor 等本地工具）
#    ./run_mcp.sh --transport streamable-http    # Streamable HTTP 模式（供远程客户端 HTTP 访问）
#
#  Streamable HTTP 模式额外参数：
#    --host 0.0.0.0     监听地址（默认 0.0.0.0）
#    --port 8888        监听端口（默认 8888）
#
#  SourcePilot 依赖：
#    如果 SOURCEPILOT_URL 未设置，脚本会自动在后台启动 SourcePilot
#    并等待其健康检查通过后再启动 MCP Server。
#
#  环境变量：
#    ZOEKT_URL        Zoekt webserver 地址 (默认 http://localhost:6070)
#    SOURCEPILOT_URL  SourcePilot API 地址 (若未设置则自动启动)
#    MCP_PORT         Streamable HTTP 监听端口 (可选，等价于 --port)
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)

# 使用 pyenv 虚拟环境
VENV_PYTHON="/opt/pyenv/versions/dify_py3_env/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
    echo "Warning: $VENV_PYTHON not found, using system python3" >&2
    VENV_PYTHON="python3"
fi

export PYTHONPATH="$DIR/../mcp-server"

# ── SourcePilot 自动启动 ──────────────────────────────
SOURCEPILOT_PID=""

cleanup() {
    if [ -n "$SOURCEPILOT_PID" ]; then
        echo "Stopping SourcePilot (PID $SOURCEPILOT_PID)..." >&2
        kill "$SOURCEPILOT_PID" 2>/dev/null || true
        wait "$SOURCEPILOT_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

if [ -z "${SOURCEPILOT_URL:-}" ]; then
    echo "SOURCEPILOT_URL not set, starting SourcePilot in background..." >&2
    "$DIR/run_sourcepilot.sh" &
    SOURCEPILOT_PID=$!

    # 等待健康检查通过
    MAX_RETRIES=30
    RETRY_INTERVAL=1
    for i in $(seq 1 $MAX_RETRIES); do
        if curl -sf http://localhost:9000/api/health >/dev/null 2>&1; then
            echo "SourcePilot is ready (PID $SOURCEPILOT_PID)" >&2
            break
        fi
        if [ "$i" -eq "$MAX_RETRIES" ]; then
            echo "Error: SourcePilot failed to start after ${MAX_RETRIES}s" >&2
            exit 1
        fi
        sleep "$RETRY_INTERVAL"
    done

    export SOURCEPILOT_URL="http://localhost:9000"
else
    echo "Using existing SourcePilot: $SOURCEPILOT_URL" >&2
fi

# ── MCP Server 启动 ───────────────────────────────────

# 如果没传参数，默认 stdio 模式
if [ $# -eq 0 ]; then
    echo "AOSP Code Search MCP Server (stdio)" >&2
    echo "Zoekt URL: ${ZOEKT_URL:-http://localhost:6070}" >&2
    echo "SourcePilot URL: $SOURCEPILOT_URL" >&2
    exec "$VENV_PYTHON" -m mcp_server
fi

# 检查是否是 streamable-http 模式，打印提示信息
for arg in "$@"; do
    if [ "$arg" = "streamable-http" ]; then
        MCP_PORT="${MCP_PORT:-8888}"
        echo "AOSP Code Search MCP Server (streamable-http)" >&2
        echo "Zoekt URL: ${ZOEKT_URL:-http://localhost:6070}" >&2
        echo "SourcePilot URL: $SOURCEPILOT_URL" >&2
        echo "MCP Endpoint: http://0.0.0.0:${MCP_PORT}/mcp" >&2
        break
    fi
done

exec "$VENV_PYTHON" -m mcp_server "$@"
