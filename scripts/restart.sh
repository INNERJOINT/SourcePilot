#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  一键重启脚本
#
#  停掉占用目标端口的进程后重新启动全栈（zoekt + SourcePilot + MCP + audit-viewer）。
#  用于修改 .env 后让配置生效。
#
#  用法：
#    ./restart.sh                 # 重启 SourcePilot + MCP + audit-viewer（默认不动 zoekt）
#    ./restart.sh --with-zoekt    # 同时重启 zoekt-webserver
#    ./restart.sh --only sp       # 只重启 SourcePilot
#    ./restart.sh --only mcp      # 只重启 MCP
#    ./restart.sh --only av       # 只重启 audit-viewer
#    ./restart.sh --stop          # 只停服务，不重启
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)
source "$DIR/_env.sh"

MCP_PORT="${MCP_PORT:-8888}"
AUDIT_VIEWER_PORT="${AUDIT_VIEWER_PORT:-9100}"
SP_PORT=9000
ZOEKT_PORT_DEFAULT=6070

WITH_ZOEKT=false
STOP_ONLY=false
ONLY=""

while [ $# -gt 0 ]; do
    case "$1" in
        --with-zoekt) WITH_ZOEKT=true ;;
        --stop) STOP_ONLY=true ;;
        --only) ONLY="${2:-}"; shift ;;
        -h|--help)
            sed -n '2,17p' "$0"
            exit 0
            ;;
        *) echo "未知参数: $1" >&2; exit 1 ;;
    esac
    shift
done

kill_port() {
    local port="$1"
    local name="$2"
    local pids
    pids=$(lsof -ti ":$port" 2>/dev/null || true)
    if [ -z "$pids" ]; then
        echo "  [$name] 端口 $port 空闲，跳过" >&2
        return
    fi
    echo "  [$name] 停止端口 $port 上的进程: $pids" >&2
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 1
    pids=$(lsof -ti ":$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "  [$name] 进程未响应，发送 SIGKILL: $pids" >&2
        # shellcheck disable=SC2086
        kill -9 $pids 2>/dev/null || true
    fi
}

# ── 停止阶段 ───────────────────────────────────────────
echo "停止服务..." >&2

if [ -z "$ONLY" ] || [ "$ONLY" = "mcp" ]; then
    kill_port "$MCP_PORT" "MCP"
fi
if [ -z "$ONLY" ] || [ "$ONLY" = "sp" ]; then
    kill_port "$SP_PORT" "SourcePilot"
fi
if [ -z "$ONLY" ] || [ "$ONLY" = "av" ]; then
    kill_port "$AUDIT_VIEWER_PORT" "audit-viewer"
fi
if [ "$WITH_ZOEKT" = true ]; then
    kill_port "$ZOEKT_PORT_DEFAULT" "zoekt-webserver"
fi

if [ "$STOP_ONLY" = true ]; then
    echo "已停止。" >&2
    exit 0
fi

# ── 启动阶段 ───────────────────────────────────────────
echo "" >&2
echo "启动服务..." >&2

case "$ONLY" in
    sp)
        exec "$DIR/run_sourcepilot.sh"
        ;;
    mcp)
        exec "$DIR/run_mcp.sh"
        ;;
    av)
        exec "$DIR/../audit-viewer/scripts/run_audit_viewer.sh"
        ;;
    "")
        exec "$DIR/run_all.sh"
        ;;
    *)
        echo "--only 只支持: sp | mcp | av" >&2
        exit 1
        ;;
esac
