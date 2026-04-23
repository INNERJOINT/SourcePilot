#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  AOSP Code Search MCP Server 启动脚本
#
#  支持两种传输模式：
#    ./run_mcp.sh                               # stdio 模式（默认，供 Claude Code / Cursor 等本地工具）
#    ./run_mcp.sh --transport streamable-http    # Streamable HTTP 模式（Docker，供远程客户端 HTTP 访问）
#
#  Streamable HTTP 模式额外参数：
#    --host 0.0.0.0     监听地址（默认 0.0.0.0）
#    --port 8888        监听端口（默认 8888）
#
#  SourcePilot 依赖：
#    stdio 模式：如果 SOURCEPILOT_URL 未设置，脚本会自动在后台启动 SourcePilot
#    streamable-http 模式：通过 Docker compose 启动 SourcePilot + MCP Server
#
#  环境变量：
#    ZOEKT_URL        Zoekt webserver 地址 (默认 http://localhost:6070)
#    SOURCEPILOT_URL  SourcePilot API 地址 (stdio 模式：若未设置则自动启动)
#    MCP_PORT         Streamable HTTP 监听端口 (可选，等价于 --port)
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)

# 加载共享库
source "$DIR/share/_common.sh"
_common_parse_help "$@"

# 加载 .env 配置（如果存在）
source "$DIR/share/_env.sh"

# ── streamable-http 模式检测 ──────────────────────────
IS_HTTP_MODE=false
for arg in "$@"; do
    if [ "$arg" = "streamable-http" ]; then
        IS_HTTP_MODE=true
        break
    fi
done

# ── streamable-http 模式：使用 Docker ────────────────
if [ "$IS_HTTP_MODE" = true ]; then
    source "$DIR/share/_infra.sh"

    MCP_PORT="${MCP_PORT:-8888}"
    SP_COCKPIT_RUNNING=false

    cleanup() {
        echo "" >&2
        info "正在停止服务..."
        docker compose -f "$COMPOSE_FILE" stop sourcepilot-gateway mcp-server 2>/dev/null || true
        info "服务已停止。"
    }
    trap cleanup EXIT INT TERM

    export SOURCEPILOT_URL="http://localhost:9000"
    infra_start_sourcepilot
    infra_start_mcp

    echo "" >&2
    echo "════════════════════════════════════════════" >&2
    echo "  MCP Server (streamable-http) 已启动：" >&2
    echo "    SourcePilot  (Docker)  (http://localhost:9000)" >&2
    echo "    MCP Server   (Docker)  (http://0.0.0.0:${MCP_PORT}/mcp)" >&2
    echo "" >&2
    echo "  按 Ctrl+C 停止服务" >&2
    echo "════════════════════════════════════════════" >&2

    # 监控 Docker 服务健康状态
    while true; do
        unhealthy=$(docker compose -f "$COMPOSE_FILE" ps --format json \
            | jq -r 'select(.Health == "unhealthy" or .State == "exited") | .Service' 2>/dev/null || true)
        if [ -n "$unhealthy" ]; then
            warn "服务异常: $unhealthy"
            break
        fi
        sleep 5
    done
    info "某个服务异常退出，正在关闭所有服务..."
    exit 0
fi

# ── stdio 模式：裸进程启动 ────────────────────────────
VENV_PYTHON="/opt/pyenv/versions/dify_py3_env/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
    echo "Warning: $VENV_PYTHON not found, using system python3" >&2
    VENV_PYTHON="python3"
fi

export PYTHONPATH="$DIR/../mcp-server"

SOURCEPILOT_PID=""

cleanup_stdio() {
    if [ -n "$SOURCEPILOT_PID" ]; then
        echo "Stopping SourcePilot (PID $SOURCEPILOT_PID)..." >&2
        kill "$SOURCEPILOT_PID" 2>/dev/null || true
        wait "$SOURCEPILOT_PID" 2>/dev/null || true
    fi
}
trap cleanup_stdio EXIT

if [ -z "${SOURCEPILOT_URL:-}" ]; then
    echo "SOURCEPILOT_URL not set, starting SourcePilot in background..." >&2
    "$DIR/share/_start_sourcepilot.sh" &
    SOURCEPILOT_PID=$!

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

echo "AOSP Code Search MCP Server (stdio)" >&2
echo "Zoekt URL: ${ZOEKT_URL:-http://localhost:6070}" >&2
echo "SourcePilot URL: $SOURCEPILOT_URL" >&2
exec "$VENV_PYTHON" -m mcp_server
