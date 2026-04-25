#!/usr/bin/env bash
# scripts/smoke_queries.sh — SourcePilot 手动 smoke 巡检
#
# 用法:
#   scripts/run_all.sh            # 先把 SourcePilot/zoekt/Qdrant/sp-cockpit 起好
#   bash scripts/smoke_queries.sh
#
# 前置条件:
#   - DENSE_ENABLED=true (SourcePilot 启动时需设置)
#   - Qdrant 运行中，frameworks/base 已完成向量索引
#   - sp-cockpit 运行中 (port 9100)，audit.db 正在被填充
#   - 审查入口: http://localhost:9100  (按 trace_id 过滤逐条人工审查)
#
# 依赖: bash + curl + jq + sqlite3 + (uuidgen 或 openssl) + GNU date (Linux)
# 端点: SourcePilot HTTP API (默认 http://localhost:9000)
# 退出码: 0 全 PASS 且 audit 通过 / 1 任一 FAIL 或 audit 失败 / 2 前置检查不通过

set -euo pipefail

source "$(dirname "$0")/../share/_common.sh"
_common_parse_help "$@"

SOURCEPILOT_URL="${SOURCEPILOT_URL:-http://localhost:9000}"
TIMEOUT="${TIMEOUT:-15}"
AUDIT_DB="${AUDIT_DB:-sp-cockpit/data/audit.db}"
# Multi-project deployments require explicit project on every call. Single-project
# deployments accept the field with no effect, so it's safe to always send it.
AOSP_PROJECT="${AOSP_PROJECT:-ace}"
RESP_FILE="$(mktemp -t smoke_resp.XXXXXX.json)"
trap 'rm -f "$RESP_FILE"' EXIT

# ─── 前置检查 ────────────────────────────────────────
for tool in curl jq sqlite3; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "ERROR: 需要 $tool，请先安装" >&2
        exit 2
    fi
done

# uuidgen 或 openssl 二选一
if ! command -v uuidgen >/dev/null 2>&1 && ! command -v openssl >/dev/null 2>&1; then
    echo "ERROR: 需要 uuidgen 或 openssl，请先安装其中之一" >&2
    exit 2
fi

if [[ ! -f "$AUDIT_DB" ]]; then
    echo "ERROR: audit.db 不存在: $AUDIT_DB" >&2
    echo "       请先运行 sp-cockpit 使其创建并填充 audit.db" >&2
    exit 2
fi

if ! curl -fsS --max-time "$TIMEOUT" "$SOURCEPILOT_URL/api/health" >/dev/null 2>&1; then
    echo "ERROR: SourcePilot 健康检查失败 (GET $SOURCEPILOT_URL/api/health)" >&2
    echo "       请先运行 scripts/run_all.sh 把服务起好" >&2
    exit 2
fi

# ─── gen_trace_id 工具函数 ────────────────────────────
gen_trace_id() {
    if command -v uuidgen >/dev/null 2>&1; then
        uuidgen | tr '[:upper:]' '[:lower:]' | tr -d '-'
    else
        openssl rand -hex 16
    fi
}

# ─── dense-enabled 探针 ──────────────────────────────
probe_tid=$(gen_trace_id)
curl -s --max-time "$TIMEOUT" \
    -o /dev/null \
    -X POST -H "content-type: application/json" \
    -H "X-Trace-Id: $probe_tid" \
    -d '{"query":"binder 驱动权限校验 probe","top_k":3}' \
    "$SOURCEPILOT_URL/api/search" 2>/dev/null || true
probe_count=0
for _ in 1 2 3; do
    sleep 1
    probe_count=$(sqlite3 "$AUDIT_DB" "SELECT count(*) FROM events WHERE stage='dense_search' AND trace_id='$probe_tid'" 2>/dev/null || echo "0")
    [[ "$probe_count" -gt 0 ]] && break
done
if [[ "$probe_count" -eq 0 ]]; then
    echo "ERROR: dense_search stage not seen after 3s. Set DENSE_ENABLED=true, ensure Qdrant is running with frameworks/base indexed, and restart SourcePilot." >&2
    exit 2
fi

# ─── 计数器 ────────────────────────────────────────
PASSED=0
FAILED=0
SKIPPED=0

# ─── 关联数组: 存储每个用例的 trace_id ───────────────
declare -A TRACE_IDS

# ─── 通用 runner ────────────────────────────────────
# run_case <name> <path> <json> <optional:yes|no> <shape:list|dict>
run_case() {
    local name="$1" path="$2" json="$3" optional="$4" shape="$5"

    local trace_id
    trace_id=$(gen_trace_id)
    TRACE_IDS["$name"]="$trace_id"

    local start http_code dur count status parse_ok=0 has_error=1

    start=$(date +%s%3N)
    http_code=$(curl -s --max-time "$TIMEOUT" \
        -o "$RESP_FILE" -w "%{http_code}" \
        -X POST -H "content-type: application/json" \
        -H "X-Trace-Id: $trace_id" \
        -d "$json" \
        "$SOURCEPILOT_URL$path" 2>/dev/null || echo "000")
    dur=$(($(date +%s%3N) - start))

    if jq -e '.' "$RESP_FILE" >/dev/null 2>&1; then
        parse_ok=1
    fi

    if [[ "$shape" == "list" ]]; then
        count=$(jq 'length' "$RESP_FILE" 2>/dev/null || echo "?")
    else
        count=1
    fi

    # dict 含 error 键 → 视为业务错误（用于 optional 降级判断）
    if jq -e 'type == "object" and has("error")' "$RESP_FILE" >/dev/null 2>&1; then
        has_error=0
    fi

    if [[ "$http_code" == "200" && $parse_ok -eq 1 && $has_error -ne 0 ]]; then
        status="PASS"
        PASSED=$((PASSED + 1))
    elif [[ "$optional" == "yes" ]]; then
        status="SKIP"
        SKIPPED=$((SKIPPED + 1))
    else
        status="FAIL"
        FAILED=$((FAILED + 1))
    fi

    printf '[%s] %-20s http=%s ms=%s count=%s trace=%s\n' \
        "$status" "$name" "$http_code" "$dur" "$count" "$trace_id"
}

# ─── 用例清单 ───────────────────────────────────────
echo "=== SourcePilot smoke @ $SOURCEPILOT_URL ==="

run_case zoekt_keyword    /api/search           "{\"query\":\"binder_open\",\"top_k\":5,\"project\":\"$AOSP_PROJECT\"}"                                                                   no  list
run_case nl_inscope_dense /api/search           "{\"query\":\"binder 驱动的权限校验机制\",\"top_k\":5,\"project\":\"$AOSP_PROJECT\"}"                                                      no  list
run_case nl_outscope_dense /api/search          "{\"query\":\"Launcher3 桌面布局加载流程\",\"top_k\":5,\"project\":\"$AOSP_PROJECT\"}"                                                     no  list
run_case symbol           /api/search_symbol    "{\"symbol\":\"startBootstrapServices\",\"top_k\":3,\"project\":\"$AOSP_PROJECT\"}"                                                        no  list
run_case file             /api/search_file      "{\"path\":\"AndroidManifest.xml\",\"top_k\":3,\"project\":\"$AOSP_PROJECT\"}"                                                             no  list
run_case regex            /api/search_regex     "{\"pattern\":\"binder_[a-z_]+\",\"top_k\":3,\"project\":\"$AOSP_PROJECT\"}"                                                               no  list
run_case list_repos       /api/list_repos       "{\"query\":\"\",\"top_k\":5,\"project\":\"$AOSP_PROJECT\"}"                                                                               no  list
run_case get_file         /api/get_file_content "{\"repo\":\"frameworks/base\",\"filepath\":\"core/java/android/os/Binder.java\",\"start_line\":1,\"end_line\":40,\"project\":\"$AOSP_PROJECT\"}" yes dict

# ─── 汇总 ─────────────────────────────────────────
echo "---"
echo "PASSED=$PASSED FAILED=$FAILED SKIPPED=$SKIPPED"
echo "(注: count=0 不算 fail；PASS 仅看 HTTP 200 + JSON 可解析)"

# ─── audit 校验 ─────────────────────────────────────
echo "--- audit verification @ $AUDIT_DB ---"
AUDIT_FAIL=0

# 3a. poll-until-present
expected=${#TRACE_IDS[@]}
ids_csv=$(printf "'%s'," "${TRACE_IDS[@]}" | sed 's/,$//')
for i in 1 2 3 4 5 6; do
    seen=$(sqlite3 "$AUDIT_DB" "SELECT count(DISTINCT trace_id) FROM events WHERE trace_id IN ($ids_csv)" 2>/dev/null || echo "0")
    [[ "$seen" -ge "$expected" ]] && break
    sleep 1
done

# 3b. stage coverage
required_stages=(classify rewrite zoekt_search dense_search nl_parallel_search rrf_merge rerank
                 search_symbol search_file search_regex list_repos get_file_content)
have=$(sqlite3 "$AUDIT_DB" "SELECT DISTINCT stage FROM events WHERE trace_id IN ($ids_csv) AND stage IS NOT NULL" 2>/dev/null || true)
for s in "${required_stages[@]}"; do
    if ! grep -qx "$s" <<<"$have"; then
        echo "[FAIL] stage missing: $s"; AUDIT_FAIL=$((AUDIT_FAIL+1))
    fi
done

# 3c. in-scope dense: records_count > 0
in_tid="${TRACE_IDS[nl_inscope_dense]}"
in_hits=$(sqlite3 "$AUDIT_DB" 'SELECT COALESCE(json_extract(payload_json,"$.stage_result.records_count"),0) FROM events WHERE trace_id='"'$in_tid'"' AND stage='"'dense_search'"' LIMIT 1' 2>/dev/null || echo "")
if [[ -z "$in_hits" || "$in_hits" -le 0 ]]; then
    echo "[FAIL] in-scope dense records_count not >0 (got: '$in_hits')"; AUDIT_FAIL=$((AUDIT_FAIL+1))
fi

# 3d. out-of-scope dense: records_count == 0 AND zoekt_routes_succeeded > 0
out_tid="${TRACE_IDS[nl_outscope_dense]}"
out_dense=$(sqlite3 "$AUDIT_DB" 'SELECT COALESCE(json_extract(payload_json,"$.stage_result.records_count"),0) FROM events WHERE trace_id='"'$out_tid'"' AND stage='"'dense_search'"' LIMIT 1' 2>/dev/null || echo "0")
[[ "$out_dense" -ne 0 ]] && { echo "[FAIL] out-of-scope dense records_count expected 0 (got: '$out_dense')"; AUDIT_FAIL=$((AUDIT_FAIL+1)); }

out_zoekt=$(sqlite3 "$AUDIT_DB" 'SELECT COALESCE(json_extract(payload_json,"$.stage_result.zoekt_routes_succeeded"),0) FROM events WHERE trace_id='"'$out_tid'"' AND stage='"'nl_parallel_search'"' LIMIT 1' 2>/dev/null || echo "0")
[[ "$out_zoekt" -le 0 ]] && { echo "[FAIL] out-of-scope zoekt_routes_succeeded expected >0 (got: '$out_zoekt')"; AUDIT_FAIL=$((AUDIT_FAIL+1)); }

echo "AUDIT_FAIL=$AUDIT_FAIL"
echo "审查入口: http://localhost:9100  (按 trace_id 过滤逐条人工审查 rewrite/RRF/rerank)"
for n in "${!TRACE_IDS[@]}"; do printf '  %-22s trace_id=%s\n' "$n" "${TRACE_IDS[$n]}"; done

# ─── 最终退出码 ───────────────────────────────────────
if (( FAILED == 0 && AUDIT_FAIL == 0 )); then
    exit 0
else
    exit 1
fi
