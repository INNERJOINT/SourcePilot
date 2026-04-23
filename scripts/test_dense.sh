#!/usr/bin/env bash
# scripts/test_dense.sh — 测试 dense search 是否被触发
#
# 用法:
#   DENSE_ENABLED=true scripts/run_sourcepilot.sh   # 先启动（需 Milvus + Embedding 服务）
#   bash scripts/test_dense.sh
#
# 前置条件:
#   - SourcePilot 以 DENSE_ENABLED=true 启动
#   - Milvus 运行中 (默认 localhost:19530)
#   - Embedding 服务运行中 (默认 localhost:8080)
#   - frameworks/base 已完成向量索引
#
# 依赖: curl + jq

set -euo pipefail

source "$(dirname "$0")/_common.sh"
_common_parse_help "$@"

SOURCEPILOT_URL="${SOURCEPILOT_URL:-http://localhost:9000}"
TIMEOUT="${TIMEOUT:-15}"
AUDIT_LOG="${AUDIT_LOG:-audit.log}"

for tool in curl jq; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "ERROR: 需要 $tool" >&2; exit 2
    fi
done

# ─── 健康检查 ────────────────────────────────────────
if ! curl -fsS --max-time "$TIMEOUT" "$SOURCEPILOT_URL/api/health" >/dev/null 2>&1; then
    echo "ERROR: SourcePilot 不可达 ($SOURCEPILOT_URL/api/health)" >&2
    exit 2
fi
echo "SourcePilot OK: $SOURCEPILOT_URL"

# ─── 生成 trace_id ───────────────────────────────────
if command -v uuidgen >/dev/null 2>&1; then
    TRACE_ID=$(uuidgen | tr '[:upper:]' '[:lower:]' | tr -d '-')
else
    TRACE_ID=$(openssl rand -hex 16)
fi

# ─── 发送 NL 查询（只有 NL 路径才会触发 dense）────────
QUERY="binder 驱动的权限校验机制"
echo ""
echo ">>> 发送 NL 查询: \"$QUERY\""
echo "    trace_id: $TRACE_ID"
echo ""

RESP=$(mktemp -t dense_test.XXXXXX.json)
trap 'rm -f "$RESP"' EXIT

HTTP_CODE=$(curl -s --max-time "$TIMEOUT" \
    -o "$RESP" -w "%{http_code}" \
    -X POST -H "content-type: application/json" \
    -H "X-Trace-Id: $TRACE_ID" \
    -d "{\"query\":\"$QUERY\",\"top_k\":5}" \
    "$SOURCEPILOT_URL/api/search" 2>/dev/null || echo "000")

if [[ "$HTTP_CODE" != "200" ]]; then
    echo "FAIL: HTTP $HTTP_CODE" >&2
    cat "$RESP" 2>/dev/null
    exit 1
fi

RESULT_COUNT=$(jq 'length' "$RESP" 2>/dev/null || echo "?")
echo "HTTP 200 — 返回 $RESULT_COUNT 条结果"

# ─── 检查结果中是否包含 dense 来源 ──────────────────
DENSE_COUNT=$(jq '[.[] | select(.source == "dense")] | length' "$RESP" 2>/dev/null || echo "0")
ZOEKT_COUNT=$(jq '[.[] | select(.source != "dense")] | length' "$RESP" 2>/dev/null || echo "0")

echo ""
echo "来源统计:"
echo "  zoekt:  $ZOEKT_COUNT 条"
echo "  dense:  $DENSE_COUNT 条"

# ─── 从 audit.log 验证 dense_search stage ────────────
echo ""
echo "--- audit.log 验证 ---"

if [[ ! -f "$AUDIT_LOG" ]]; then
    echo "WARN: $AUDIT_LOG 不存在，跳过 audit 验证"
    echo "      可设置 AUDIT_LOG 指向实际路径"
else
    sleep 1
    DENSE_STAGE=$(grep "$TRACE_ID" "$AUDIT_LOG" | grep '"dense_search"' | head -1)
    if [[ -n "$DENSE_STAGE" ]]; then
        records=$(echo "$DENSE_STAGE" | jq -r '.stage_result.records_count // 0' 2>/dev/null || echo "?")
        echo "[PASS] dense_search stage 已触发 (records_count=$records)"
    else
        echo "[FAIL] dense_search stage 未出现在 audit.log 中"
        echo "       可能原因:"
        echo "       1. DENSE_ENABLED 未设为 true"
        echo "       2. 查询未被 classifier 分类为 NL 意图"
        echo "       3. Milvus/Embedding 服务连接失败"
        exit 1
    fi

    # 展示本次 trace 的完整 stage 链
    echo ""
    echo "本次请求 stage 链:"
    grep "$TRACE_ID" "$AUDIT_LOG" | jq -r '"  " + .stage + " → " + (.stage_result // {} | tostring | .[0:80])' 2>/dev/null || true
fi

echo ""
if [[ "$DENSE_COUNT" -gt 0 ]]; then
    echo "PASS: dense search 已触发且返回了结果"
    exit 0
else
    echo "WARN: dense search 可能已触发但未返回匹配结果 (collection 中可能无相关数据)"
    exit 0
fi
