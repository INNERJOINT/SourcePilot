#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  SourcePilot 全栈启动脚本（不含 MCP）
#
#  启动顺序：
#    1. sparse-index-zoekt（索引服务）
#    2. Dense 检索栈（qdrant/dense-index-coderankembed，DENSE_ENABLED=true 时）
#    3. Neo4j 结构化检索（STRUCTURAL_ENABLED=true 时）
#    4. SourcePilot（搜索引擎 API，Docker，端口 9000）
#    5. sp-cockpit（审计面板，Docker，端口 9100）
#
#  用法：
#    ./run_sourcepilot.sh                       # 启动 zoekt + SourcePilot + sp-cockpit
#    DENSE_ENABLED=true ./run_sourcepilot.sh    # 包含 Dense 检索栈
#    STRUCTURAL_ENABLED=true ./run_sourcepilot.sh    # 包含 Neo4j 结构化检索
#    ./run_sourcepilot.sh --bare                # 仅启动 SourcePilot 进程（等同旧行为）
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)

# 加载共享库
source "$DIR/share/_common.sh"
_common_parse_help "$@"
source "$DIR/share/_env.sh"
source "$DIR/share/_infra.sh"

# ── --bare 模式：直接转发给 _start_sourcepilot.sh ─────────
for arg in "$@"; do
    if [ "$arg" = "--bare" ]; then
        shift
        exec "$DIR/share/_start_sourcepilot.sh" "$@"
    fi
done

# ── 配置 ──────────────────────────────────────────────
ZOEKT_URL="${ZOEKT_URL:-http://localhost:6070}"
SP_COCKPIT_PORT="${SP_COCKPIT_PORT:-9100}"
SP_COCKPIT_ENABLED="${SP_COCKPIT_ENABLED:-true}"

# ── 进程管理 ──────────────────────────────────────────
PIDS=()
SP_COCKPIT_RUNNING=false
ZOEKT_DOCKER=false

cleanup() {
    echo "" >&2
    info "正在停止所有服务..."
    docker compose -f "$COMPOSE_FILE" stop sourcepilot-gateway sp-cockpit 2>/dev/null || true
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

# ── 1. 启动 sparse-index-zoekt ──────────────────────────
infra_start_zoekt

# ── 2. 启动 Dense 检索栈 ─────────────────────────────
infra_start_dense

# ── 3. 启动 Neo4j ────────────────────────────────────
infra_start_structural

# ── 4. 启动 SourcePilot ──────────────────────────────
infra_start_sourcepilot

# ── 5. 启动 sp-cockpit ───────────────────────────────
infra_start_cockpit

# ── 启动完成 ──────────────────────────────────────────
echo "" >&2
echo "════════════════════════════════════════════" >&2
echo "  所有服务已启动（不含 MCP）：" >&2
if [ "$ZOEKT_DOCKER" = true ]; then
echo "    sparse-index-zoekt  (Docker)       ($ZOEKT_URL)" >&2
else
echo "    sparse-index-zoekt  PID ${PIDS[0]:-?}  ($ZOEKT_URL)" >&2
fi
if [ "${DENSE_ENABLED:-false}" = "true" ]; then
echo "    Dense 检索栈     (Docker)       (Qdrant :6333)" >&2
fi
if [ "${STRUCTURAL_ENABLED:-false}" = "true" ]; then
echo "    Neo4j            (Docker)       (bolt://localhost:7687)" >&2
fi
echo "    SourcePilot      (Docker)       (http://localhost:9000)" >&2
if [ "$SP_COCKPIT_ENABLED" = "true" ]; then
    if [ "$SP_COCKPIT_RUNNING" = true ]; then
        echo "    sp-cockpit       (Docker)       (http://localhost:${SP_COCKPIT_PORT})" >&2
    else
        echo "    sp-cockpit       (启动失败/超时)" >&2
    fi
fi
echo "" >&2
echo "  按 Ctrl+C 停止所有服务" >&2
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
