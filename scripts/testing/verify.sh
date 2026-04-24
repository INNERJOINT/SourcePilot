#!/usr/bin/env bash
# verify.sh — unified verification for structural audit and indexer containers
#
# Usage:
#   scripts/verify.sh structural-audit
#   scripts/verify.sh indexer-containers
#
# Subcommands:
#   structural-audit     — Structural 审计事件端到端验证
#   indexer-containers   — 验证 dense/structural indexer 在 docker-compose.yml 中定义正确
set -euo pipefail
source "$(dirname "$0")/../share/_common.sh"
_common_parse_help "$@"

# ─── structural-audit ──────────────────────────────────────────────────────────

_run_structural_audit() {
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

    info "检查 STRUCTURAL_ENABLED 环境变量..."
    local STRUCTURAL_ENABLED_STATUS
    STRUCTURAL_ENABLED_STATUS=$(curl -sf "${SOURCEPILOT_URL}/health" | grep -o '"structural":[^,}]*' || echo "unknown")
    info "structural 状态: ${STRUCTURAL_ENABLED_STATUS}"

    info "检查 audit.db..."
    if [ ! -f "${AUDIT_DB}" ]; then
        log ERROR "audit.db 不存在: ${AUDIT_DB}"
        echo "sp-cockpit 尚未摄取日志，请等待 30s 后重试"
        return 1
    fi
    info "audit.db 存在"

    # ─── 发送测试查询 ─────────────────────────────────────────────────────────

    info "发送 3 条测试查询..."

    local TRACE_PREFIX="trace-structural-verify-$$"
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

    # ─── 验证 structural_search 事件 ──────────────────────────────────────────────

    info "查询 audit.db 中的 structural_search 事件..."

    local STRUCTURAL_COUNT
    STRUCTURAL_COUNT=$(sqlite3 "${AUDIT_DB}" \
        "SELECT count(*) FROM events WHERE json_extract(data, '\$.stage') = 'structural_search'" \
        2>/dev/null || echo "0")

    echo "structural_search 事件数: ${STRUCTURAL_COUNT}"

    if [ "${STRUCTURAL_COUNT}" -gt 0 ]; then
        info "structural_search 事件已记录 (共 ${STRUCTURAL_COUNT} 条)"
    else
        log ERROR "未找到 structural_search 事件 (STRUCTURAL_ENABLED 是否为 true?)"
        echo ""
        echo "调试步骤:"
        echo "  1. 确认 STRUCTURAL_ENABLED=true 已设置"
        echo "  2. 确认 Neo4j 可访问且结构化索引已建索引"
        echo "  3. 查看 audit.log: tail -50 /mnt/code/T2/Dify/audit.log | grep structural_search"
    fi

    # ─── 延迟对比报告 ────────────────────────────────────────────────────────

    echo ""
    info "各 lane 延迟对比 (最近 30 条, 按 duration_ms 降序):"
    echo "────────────────────────────────────────────────────"
    sqlite3 "${AUDIT_DB}" \
        "SELECT json_extract(data, '\$.stage') AS stage,
                printf('%.1f', json_extract(data, '\$.duration_ms')) AS ms
         FROM events
         WHERE json_extract(data, '\$.stage') IN ('zoekt_search','dense_search','structural_search')
         ORDER BY CAST(json_extract(data, '\$.duration_ms') AS REAL) DESC
         LIMIT 30" \
        2>/dev/null | column -t -s '|' || echo "(无数据)"
    echo "────────────────────────────────────────────────────"

    # ─── 汇总 ────────────────────────────────────────────────────────────────

    echo ""
    if [ "${STRUCTURAL_COUNT}" -gt 0 ]; then
        info "Structural 审计验证通过：structural_search 事件端到端正常"
        return 0
    else
        log ERROR "Structural 审计验证失败：未找到 structural_search 事件"
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
    _check "deploy compose config (default profile — 不应含 dense-indexer/structural-indexer)" \
        bash -c "svc=\$(docker compose -f '$COMPOSE' config --services); echo \"\$svc\" | grep -vq '^dense-indexer\$' && echo \"\$svc\" | grep -vq '^structural-indexer\$'"
    _check "deploy compose project name = dify" \
        bash -c "docker compose -f '$COMPOSE' config | grep -E '^name:' | grep -q 'dify'"
    _check "root shim resolves to deploy compose" \
        docker compose -f "$DIR/docker-compose.yml" config -q

    if [[ "${INDEXER_RUN_HELP:-0}" = "1" ]]; then
        _check "dense-indexer --help" \
            docker compose -f "$COMPOSE" --profile indexer run --rm dense-indexer --help
        _check "structural-indexer --help" \
            docker compose -f "$COMPOSE" --profile indexer run --rm structural-indexer --help
    fi

    return "$fail"
}

# ─── dispatch ────────────────────────────────────────────────────────────────

case "${1:-}" in
    structural-audit)    shift; _run_structural_audit "$@" ;;
    indexer-containers)  shift; _run_indexer_containers "$@" ;;
    *)                   die "Usage: verify.sh <structural-audit|indexer-containers>" ;;
esac
