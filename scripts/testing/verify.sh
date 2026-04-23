#!/usr/bin/env bash
# verify.sh — unified verification for graphrag audit and indexer containers
#
# Usage:
#   scripts/verify.sh graphrag-audit
#   scripts/verify.sh indexer-containers
#
# Subcommands:
#   graphrag-audit       — GraphRAG 审计事件端到端验证
#   indexer-containers   — 验证 dense/graph indexer 在 docker-compose.yml 中定义正确
set -euo pipefail
source "$(dirname "$0")/../share/_common.sh"
_common_parse_help "$@"

# ─── graphrag-audit ──────────────────────────────────────────────────────────

_run_graphrag_audit() {
    local SOURCEPILOT_URL="${SOURCEPILOT_URL:-http://localhost:9000}"
    local SP_COCKPIT_URL="${SP_COCKPIT_URL:-http://localhost:9100}"
    local AUDIT_DB="${AUDIT_DB:-/mnt/code/T2/Dify/sp-cockpit/data/audit.db}"

    info "检查 sp-cockpit 健康状态..."
    if ! curl -sf "${SP_COCKPIT_URL}/api/health" > /dev/null 2>&1; then
        log ERROR "sp-cockpit 未响应 (${SP_COCKPIT_URL}/api/health)"
        echo ""
        echo "请先启动 sp-cockpit:"
        echo "  cd /mnt/code/T2/Dify && bash scripts/run_all.sh"
        echo "  # 或单独启动: cd sp-cockpit && uvicorn main:app --port 9100"
        return 1
    fi
    info "sp-cockpit 响应正常"

    info "检查 SourcePilot 健康状态..."
    if ! curl -sf "${SOURCEPILOT_URL}/health" > /dev/null 2>&1; then
        log ERROR "SourcePilot 未响应 (${SOURCEPILOT_URL}/health)"
        return 1
    fi
    info "SourcePilot 响应正常"

    info "检查 GRAPH_ENABLED 环境变量..."
    local GRAPH_ENABLED_STATUS
    GRAPH_ENABLED_STATUS=$(curl -sf "${SOURCEPILOT_URL}/health" | grep -o '"graph":[^,}]*' || echo "unknown")
    info "graph 状态: ${GRAPH_ENABLED_STATUS}"

    info "检查 audit.db..."
    if [ ! -f "${AUDIT_DB}" ]; then
        log ERROR "audit.db 不存在: ${AUDIT_DB}"
        echo "sp-cockpit 尚未摄取日志，请等待 30s 后重试"
        return 1
    fi
    info "audit.db 存在"

    # ─── 发送测试查询 ─────────────────────────────────────────────────────────

    info "发送 3 条测试查询..."

    local TRACE_PREFIX="trace-graphrag-verify-$$"
    local i TRACE_ID QUERY HTTP_STATUS

    for i in 1 2 3; do
        TRACE_ID="${TRACE_PREFIX}-${i}"
        QUERY="startActivity intent android"
        case $i in
            2) QUERY="BroadcastReceiver register filter" ;;
            3) QUERY="WindowManagerService token window" ;;
        esac

        HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
            -X POST "${SOURCEPILOT_URL}/api/search" \
            -H "Content-Type: application/json" \
            -H "X-Trace-Id: ${TRACE_ID}" \
            -d "{\"query\": \"${QUERY}\", \"top_k\": 5}" \
            2>/dev/null || echo "000")

        if [ "${HTTP_STATUS}" = "200" ]; then
            info "查询 ${i} 成功 (trace: ${TRACE_ID})"
        else
            log ERROR "查询 ${i} 失败 (HTTP ${HTTP_STATUS}, trace: ${TRACE_ID})"
        fi
    done

    # ─── 等待摄取 ─────────────────────────────────────────────────────────────

    info "等待 sp-cockpit 摄取日志 (3s)..."
    sleep 3

    # ─── 验证 graph_search 事件 ──────────────────────────────────────────────

    info "查询 audit.db 中的 graph_search 事件..."

    local GRAPH_COUNT
    GRAPH_COUNT=$(sqlite3 "${AUDIT_DB}" \
        "SELECT count(*) FROM events WHERE json_extract(data, '\$.stage') = 'graph_search'" \
        2>/dev/null || echo "0")

    echo "graph_search 事件数: ${GRAPH_COUNT}"

    if [ "${GRAPH_COUNT}" -gt 0 ]; then
        info "graph_search 事件已记录 (共 ${GRAPH_COUNT} 条)"
    else
        log ERROR "未找到 graph_search 事件 (GRAPH_ENABLED 是否为 true?)"
        echo ""
        echo "调试步骤:"
        echo "  1. 确认 GRAPH_ENABLED=true 已设置"
        echo "  2. 确认 Neo4j 可访问且图谱已建索引"
        echo "  3. 查看 audit.log: tail -50 /mnt/code/T2/Dify/audit.log | grep graph_search"
    fi

    # ─── 延迟对比报告 ────────────────────────────────────────────────────────

    echo ""
    info "各 lane 延迟对比 (最近 30 条, 按 duration_ms 降序):"
    echo "────────────────────────────────────────────────────"
    sqlite3 "${AUDIT_DB}" \
        "SELECT json_extract(data, '\$.stage') AS stage,
                printf('%.1f', json_extract(data, '\$.duration_ms')) AS ms
         FROM events
         WHERE json_extract(data, '\$.stage') IN ('zoekt_search','dense_search','graph_search')
         ORDER BY CAST(json_extract(data, '\$.duration_ms') AS REAL) DESC
         LIMIT 30" \
        2>/dev/null | column -t -s '|' || echo "(无数据)"
    echo "────────────────────────────────────────────────────"

    # ─── 汇总 ────────────────────────────────────────────────────────────────

    echo ""
    if [ "${GRAPH_COUNT}" -gt 0 ]; then
        info "GraphRAG 审计验证通过：graph_search 事件端到端正常"
        return 0
    else
        log ERROR "GraphRAG 审计验证失败：未找到 graph_search 事件"
        return 1
    fi
}

# ─── indexer-containers ──────────────────────────────────────────────────────

_run_indexer_containers() {
    local DIR
    DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
    local COMPOSE="$DIR/deploy/docker-compose.yml"
    local AOSP_SOURCE_ROOT="${AOSP_SOURCE_ROOT:-/mnt/code/ACE}"
    export AOSP_SOURCE_ROOT

    local fail=0

    _check() {
        local label="$1"; shift
        echo "==> $label"
        if "$@"; then
            echo "    OK"
        else
            echo "    FAIL ($*)" >&2
            fail=1
        fi
    }

    if ! command -v docker >/dev/null 2>&1; then
        echo "docker 未安装；跳过验证。"
        return 0
    fi

    _check "deploy compose config (profile=indexer)" \
        docker compose -f "$COMPOSE" --profile indexer config -q
    _check "deploy compose config (default profile — 不应含 dense-indexer/graph-indexer)" \
        bash -c "svc=\$(docker compose -f '$COMPOSE' config --services); echo \"\$svc\" | grep -vq '^dense-indexer\$' && echo \"\$svc\" | grep -vq '^graph-indexer\$'"
    _check "deploy compose project name = dify" \
        bash -c "docker compose -f '$COMPOSE' config | grep -E '^name:' | grep -q 'dify'"
    _check "root shim resolves to deploy compose" \
        docker compose -f "$DIR/docker-compose.yml" config -q

    if [[ "${INDEXER_RUN_HELP:-0}" = "1" ]]; then
        _check "dense-indexer --help" \
            docker compose -f "$COMPOSE" --profile indexer run --rm dense-indexer --help
        _check "graph-indexer --help" \
            docker compose -f "$COMPOSE" --profile indexer run --rm graph-indexer --help
    fi

    return "$fail"
}

# ─── dispatch ────────────────────────────────────────────────────────────────

case "${1:-}" in
    graphrag-audit)      shift; _run_graphrag_audit "$@" ;;
    indexer-containers)  shift; _run_indexer_containers "$@" ;;
    *)                   die "Usage: verify.sh <graphrag-audit|indexer-containers>" ;;
esac
