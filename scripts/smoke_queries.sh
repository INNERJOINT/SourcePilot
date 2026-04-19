#!/usr/bin/env bash
# scripts/smoke_queries.sh — SourcePilot 手动 smoke 巡检
#
# 用法:
#   scripts/run_all.sh            # 先把 SourcePilot/zoekt 起好
#   bash scripts/smoke_queries.sh
#
# 依赖: bash + curl + jq + GNU date (Linux)
# 端点: SourcePilot HTTP API (默认 http://localhost:9000)
# 退出码: 0 全 PASS / 1 任一 FAIL / 2 前置检查不通过

set -uo pipefail

SOURCEPILOT_URL="${SOURCEPILOT_URL:-http://localhost:9000}"
TIMEOUT="${TIMEOUT:-15}"
RESP_FILE="$(mktemp -t smoke_resp.XXXXXX.json)"
trap 'rm -f "$RESP_FILE"' EXIT

# ─── 前置检查 ────────────────────────────────────────
for tool in curl jq; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "ERROR: 需要 $tool，请先安装" >&2
        exit 2
    fi
done

if ! curl -fsS --max-time "$TIMEOUT" "$SOURCEPILOT_URL/api/health" >/dev/null 2>&1; then
    echo "ERROR: SourcePilot 健康检查失败 (GET $SOURCEPILOT_URL/api/health)" >&2
    echo "       请先运行 scripts/run_all.sh 把服务起好" >&2
    exit 2
fi

# ─── 计数器 ────────────────────────────────────────
PASSED=0
FAILED=0
SKIPPED=0

# ─── 通用 runner ────────────────────────────────────
# run_case <name> <path> <json> <optional:yes|no> <shape:list|dict>
run_case() {
    local name="$1" path="$2" json="$3" optional="$4" shape="$5"

    local start http_code dur count status parse_ok=0 has_error=1

    start=$(date +%s%3N)
    http_code=$(curl -s --max-time "$TIMEOUT" \
        -o "$RESP_FILE" -w "%{http_code}" \
        -X POST -H "content-type: application/json" \
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

    printf '[%s] %-16s http=%s ms=%s count=%s\n' \
        "$status" "$name" "$http_code" "$dur" "$count"
}

# ─── 用例清单 ───────────────────────────────────────
echo "=== SourcePilot smoke @ $SOURCEPILOT_URL ==="

run_case zoekt_keyword   /api/search           '{"query":"binder_open","top_k":5}'                                                                  no  list
run_case nl_query        /api/search           '{"query":"如何启动 binder 驱动","top_k":5}'                                                          no  list
run_case dense_semantic  /api/search           '{"query":"权限校验流程","top_k":5}'                                                                  yes list
run_case symbol          /api/search_symbol    '{"symbol":"startBootstrapServices","top_k":3}'                                                       no  list
run_case file            /api/search_file      '{"path":"AndroidManifest.xml","top_k":3}'                                                            no  list
run_case regex           /api/search_regex     '{"pattern":"binder_[a-z_]+","top_k":3}'                                                              no  list
run_case list_repos      /api/list_repos       '{"query":"","top_k":5}'                                                                              no  list
run_case get_file        /api/get_file_content '{"repo":"frameworks/base","filepath":"core/java/android/os/Binder.java","start_line":1,"end_line":40}' yes dict

# ─── 汇总 ─────────────────────────────────────────
echo "---"
echo "PASSED=$PASSED FAILED=$FAILED SKIPPED=$SKIPPED"
echo "(注: count=0 不算 fail；PASS 仅看 HTTP 200 + JSON 可解析)"

if (( FAILED == 0 )); then
    exit 0
else
    exit 1
fi
