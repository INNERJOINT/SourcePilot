#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  一键重启脚本
#
#  停掉占用目标端口的进程后重新启动。
#  用于修改 .env 后让配置生效。
#
#  用法：
#    ./restart.sh                      # 重启全栈（run_all.sh）
#    ./restart.sh --with-zoekt         # 同时重启 zoekt-webserver
#    ./restart.sh --only sp            # 只重启 SourcePilot 进程
#    ./restart.sh --only mcp           # 只重启 MCP
#    ./restart.sh --only av            # 只重启 sp-cockpit
#    ./restart.sh --only sourcepilot   # 重启 SourcePilot 全栈（不含 MCP）
#    ./restart.sh --only dense         # 重启 Dense 检索栈（docker compose）
#    ./restart.sh --only graph         # 重启 Neo4j（docker compose）
#    ./restart.sh --stop               # 只停服务，不重启
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)
source "$DIR/_common.sh"
source "$DIR/_env.sh"

COMPOSE_FILE="$DIR/../deploy/docker-compose.yml"
MCP_PORT="${MCP_PORT:-8888}"
SP_COCKPIT_PORT="${SP_COCKPIT_PORT:-9100}"
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
            sed -n '2,20p' "$0"
            exit 0
            ;;
        *) die "未知参数: $1" ;;
    esac
    shift
done

kill_port() {
    local port="$1"
    local name="$2"
    local pids
    pids=$(lsof -ti ":$port" 2>/dev/null || true)
    if [ -z "$pids" ]; then
        info "[$name] 端口 $port 空闲，跳过"
        return
    fi
    info "[$name] 停止端口 $port 上的进程: $pids"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 1
    pids=$(lsof -ti ":$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        warn "[$name] 进程未响应，发送 SIGKILL: $pids"
        # shellcheck disable=SC2086
        kill -9 $pids 2>/dev/null || true
    fi
}

# ── 停止阶段 ───────────────────────────────────────────
info "停止服务..."

case "$ONLY" in
    dense)
        info "重启 Dense 检索栈 (etcd + minio + milvus + embedding-server)..."
        docker compose -f "$COMPOSE_FILE" restart etcd minio milvus embedding-server
        info "Dense 检索栈已重启"
        exit 0
        ;;
    graph)
        info "重启 Neo4j..."
        docker compose -f "$COMPOSE_FILE" restart neo4j
        info "Neo4j 已重启"
        exit 0
        ;;
    sourcepilot)
        # 停止 SourcePilot 全栈相关端口（不含 MCP）
        kill_port "$SP_PORT" "SourcePilot"
        kill_port "$SP_COCKPIT_PORT" "sp-cockpit"
        if [ "$WITH_ZOEKT" = true ]; then
            kill_port "$ZOEKT_PORT_DEFAULT" "zoekt-webserver"
        fi
        if [ "$STOP_ONLY" = true ]; then
            info "已停止。"
            exit 0
        fi
        info ""
        info "启动服务..."
        exec "$DIR/run_sourcepilot.sh"
        ;;
    mcp)
        kill_port "$MCP_PORT" "MCP"
        ;;
    sp)
        kill_port "$SP_PORT" "SourcePilot"
        ;;
    av)
        kill_port "$SP_COCKPIT_PORT" "sp-cockpit"
        ;;
    "")
        kill_port "$MCP_PORT" "MCP"
        kill_port "$SP_PORT" "SourcePilot"
        kill_port "$SP_COCKPIT_PORT" "sp-cockpit"
        if [ "$WITH_ZOEKT" = true ]; then
            kill_port "$ZOEKT_PORT_DEFAULT" "zoekt-webserver"
        fi
        ;;
    *)
        die "--only 只支持: sp | mcp | av | sourcepilot | dense | graph"
        ;;
esac

if [ "$STOP_ONLY" = true ]; then
    info "已停止。"
    exit 0
fi

# ── 启动阶段 ───────────────────────────────────────────
echo "" >&2
info "启动服务..."

case "$ONLY" in
    sp)
        exec "$DIR/_start_sourcepilot.sh"
        ;;
    mcp)
        exec "$DIR/run_mcp.sh"
        ;;
    av)
        exec "$DIR/../sp-cockpit/scripts/run_sp_cockpit.sh"
        ;;
    "")
        exec "$DIR/run_all.sh"
        ;;
esac
