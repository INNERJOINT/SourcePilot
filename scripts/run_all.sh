#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  AOSP Code Search 一键启动脚本
#
#  启动顺序：
#    1. zoekt-webserver（索引服务）
#    2. Dense 检索栈（DENSE_ENABLED=true 时）
#    3. Neo4j 图谱（GRAPH_ENABLED=true 时）
#    4. SourcePilot（搜索引擎 API）
#    5. MCP Server（协议代理）
#    6. sp-cockpit（审计面板）
#
#  配置：
#    从 .env 文件读取配置（参见 .env.example）
#    也可通过命令行环境变量覆盖
#
#  用法：
#    ./run_all.sh                           # 使用 .env 配置
#    ZOEKT_INDEX_PATH=/path ./run_all.sh    # 覆盖索引路径
#    DENSE_ENABLED=true ./run_all.sh        # 包含 Dense 检索栈
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)

# 加载共享库
source "$DIR/share/_common.sh"
_common_parse_help "$@"
source "$DIR/share/_env.sh"
source "$DIR/share/_infra.sh"

# ── 配置 ──────────────────────────────────────────────
ZOEKT_URL="${ZOEKT_URL:-http://localhost:6070}"
MCP_TRANSPORT="${MCP_TRANSPORT:-streamable-http}"
MCP_PORT="${MCP_PORT:-8888}"
SP_COCKPIT_PORT="${SP_COCKPIT_PORT:-9100}"
SP_COCKPIT_ENABLED="${SP_COCKPIT_ENABLED:-true}"

# ── 进程管理 ──────────────────────────────────────────
PIDS=()
SP_COCKPIT_PID=""
SP_COCKPIT_RUNNING=false
ZOEKT_DOCKER=false

cleanup() {
    echo "" >&2
    info "正在停止所有服务..."
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    sleep 1
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null || true
    info "所有服务已停止。"
}
trap cleanup EXIT INT TERM

# ── 1. 启动 zoekt-webserver ──────────────────────────
infra_start_zoekt

# ── 2. 启动 Dense 检索栈 ─────────────────────────────
infra_start_dense

# ── 3. 启动 Neo4j ────────────────────────────────────
infra_start_graph

# ── 4. 启动 SourcePilot ──────────────────────────────
info "启动 SourcePilot (port 9000)..."
"$DIR/share/_start_sourcepilot.sh" &
PIDS+=($!)
SP_PID=${PIDS[-1]}

for i in $(seq 1 $MAX_RETRIES); do
    if curl -sf http://localhost:9000/api/health >/dev/null 2>&1; then
        info "SourcePilot 就绪 (PID $SP_PID)"
        break
    fi
    if [ "$i" -eq "$MAX_RETRIES" ]; then
        die "SourcePilot 启动超时 (${MAX_RETRIES}s)"
    fi
    sleep 1
done

# ── 5. 启动 MCP Server ───────────────────────────────
export SOURCEPILOT_URL="http://localhost:9000"

info "启动 MCP Server (${MCP_TRANSPORT}, port ${MCP_PORT})..."

MCP_ARGS=()
if [ "$MCP_TRANSPORT" != "stdio" ]; then
    MCP_ARGS+=(--transport "$MCP_TRANSPORT" --port "$MCP_PORT")
fi

"$DIR/run_mcp.sh" "${MCP_ARGS[@]}" &
PIDS+=($!)
MCP_PID=${PIDS[-1]}

# ── 6. 启动 sp-cockpit ───────────────────────────────
infra_start_cockpit

# ── 启动完成 ──────────────────────────────────────────
echo "" >&2
echo "════════════════════════════════════════════" >&2
echo "  所有服务已启动：" >&2
if [ "$ZOEKT_DOCKER" = true ]; then
echo "    zoekt-webserver  (Docker)       ($ZOEKT_URL)" >&2
else
echo "    zoekt-webserver  PID ${PIDS[0]:-?}  ($ZOEKT_URL)" >&2
fi
if [ "${DENSE_ENABLED:-false}" = "true" ]; then
echo "    Dense 检索栈     (Docker)       (Milvus :19530)" >&2
fi
if [ "${GRAPH_ENABLED:-false}" = "true" ]; then
echo "    Neo4j            (Docker)       (bolt://localhost:7687)" >&2
fi
echo "    SourcePilot      PID $SP_PID    (http://localhost:9000)" >&2
if [ "$MCP_TRANSPORT" != "stdio" ]; then
echo "    MCP Server       PID $MCP_PID   (http://0.0.0.0:${MCP_PORT}/mcp)" >&2
else
echo "    MCP Server       PID $MCP_PID   (stdio)" >&2
fi
if [ "$SP_COCKPIT_ENABLED" = "true" ]; then
    if [ -n "${SP_COCKPIT_PID:-}" ]; then
        echo "    sp-cockpit       PID $SP_COCKPIT_PID  (http://localhost:${SP_COCKPIT_PORT})" >&2
    elif [ "$SP_COCKPIT_RUNNING" = true ]; then
        echo "    sp-cockpit       (already running)     (http://localhost:${SP_COCKPIT_PORT})" >&2
    else
        echo "    sp-cockpit       (启动失败/超时)" >&2
    fi
fi
echo "" >&2
echo "  按 Ctrl+C 停止所有服务" >&2
echo "════════════════════════════════════════════" >&2

# 等待任意子进程退出
wait -n 2>/dev/null || true
info "某个服务异常退出，正在关闭所有服务..."
