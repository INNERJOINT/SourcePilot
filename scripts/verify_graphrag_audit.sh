#!/usr/bin/env bash
# verify_graphrag_audit.sh — GraphRAG 审计事件端到端验证脚本
#
# 用途: 在完整栈（SourcePilot + audit-viewer + Neo4j）启动后运行，
#       验证 graph_search 事件正确写入 audit.db。
#
# 使用方式:
#   bash scripts/verify_graphrag_audit.sh
#
# 前提条件:
#   - SourcePilot 运行在 http://localhost:9000
#   - audit-viewer 运行在 http://localhost:9100
#   - Neo4j 运行且 GRAPH_ENABLED=true 已设置

set -euo pipefail

SOURCEPILOT_URL="${SOURCEPILOT_URL:-http://localhost:9000}"
AUDIT_VIEWER_URL="${AUDIT_VIEWER_URL:-http://localhost:9100}"
AUDIT_DB="${AUDIT_DB:-/mnt/code/T2/Dify/audit-viewer/data/audit.db}"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }
info() { echo -e "${YELLOW}[INFO]${NC} $1"; }

# ─── 前置检查 ─────────────────────────────────────────────────────────────────

info "检查 audit-viewer 健康状态..."
if ! curl -sf "${AUDIT_VIEWER_URL}/api/health" > /dev/null 2>&1; then
    fail "audit-viewer 未响应 (${AUDIT_VIEWER_URL}/api/health)"
    echo ""
    echo "请先启动 audit-viewer:"
    echo "  cd /mnt/code/T2/Dify && bash scripts/run_all.sh"
    echo "  # 或单独启动: cd audit-viewer && uvicorn main:app --port 9100"
    exit 1
fi
pass "audit-viewer 响应正常"

info "检查 SourcePilot 健康状态..."
if ! curl -sf "${SOURCEPILOT_URL}/health" > /dev/null 2>&1; then
    fail "SourcePilot 未响应 (${SOURCEPILOT_URL}/health)"
    exit 1
fi
pass "SourcePilot 响应正常"

info "检查 GRAPH_ENABLED 环境变量..."
GRAPH_ENABLED_STATUS=$(curl -sf "${SOURCEPILOT_URL}/health" | grep -o '"graph":[^,}]*' || echo "unknown")
info "graph 状态: ${GRAPH_ENABLED_STATUS}"

info "检查 audit.db..."
if [ ! -f "${AUDIT_DB}" ]; then
    fail "audit.db 不存在: ${AUDIT_DB}"
    echo "audit-viewer 尚未摄取日志，请等待 30s 后重试"
    exit 1
fi
pass "audit.db 存在"

# ─── 发送测试查询 ─────────────────────────────────────────────────────────────

info "发送 3 条测试查询..."

TRACE_PREFIX="trace-graphrag-verify-$$"

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
        pass "查询 ${i} 成功 (trace: ${TRACE_ID})"
    else
        fail "查询 ${i} 失败 (HTTP ${HTTP_STATUS}, trace: ${TRACE_ID})"
    fi
done

# ─── 等待摄取 ─────────────────────────────────────────────────────────────────

info "等待 audit-viewer 摄取日志 (3s)..."
sleep 3

# ─── 验证 graph_search 事件 ──────────────────────────────────────────────────

info "查询 audit.db 中的 graph_search 事件..."

GRAPH_COUNT=$(sqlite3 "${AUDIT_DB}" \
    "SELECT count(*) FROM events WHERE json_extract(data, '\$.stage') = 'graph_search'" \
    2>/dev/null || echo "0")

echo "graph_search 事件数: ${GRAPH_COUNT}"

if [ "${GRAPH_COUNT}" -gt 0 ]; then
    pass "graph_search 事件已记录 (共 ${GRAPH_COUNT} 条)"
else
    fail "未找到 graph_search 事件 (GRAPH_ENABLED 是否为 true?)"
    echo ""
    echo "调试步骤:"
    echo "  1. 确认 GRAPH_ENABLED=true 已设置"
    echo "  2. 确认 Neo4j 可访问且图谱已建索引"
    echo "  3. 查看 audit.log: tail -50 /mnt/code/T2/Dify/audit.log | grep graph_search"
fi

# ─── 延迟对比报告 ────────────────────────────────────────────────────────────

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

# ─── 汇总 ────────────────────────────────────────────────────────────────────

echo ""
if [ "${GRAPH_COUNT}" -gt 0 ]; then
    pass "GraphRAG 审计验证通过：graph_search 事件端到端正常"
    exit 0
else
    fail "GraphRAG 审计验证失败：未找到 graph_search 事件"
    exit 1
fi
