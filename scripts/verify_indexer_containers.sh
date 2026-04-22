#!/usr/bin/env bash
# 验证 dense-indexer / graph-indexer 在合并后的 deploy/docker-compose.yml
# 中合法定义，且 indexer profile 与默认 profile 行为正确。
#
# 用法: ./scripts/verify_indexer_containers.sh
set -uo pipefail

DIR=$(cd "$(dirname "$0")/.." && pwd)
COMPOSE="$DIR/deploy/docker-compose.yml"
AOSP_SOURCE_ROOT="${AOSP_SOURCE_ROOT:-/mnt/code/ACE}"
export AOSP_SOURCE_ROOT

fail=0

check() {
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
    exit 0
fi

check "deploy compose config (profile=indexer)" \
    docker compose -f "$COMPOSE" --profile indexer config -q
check "deploy compose config (default profile — 不应含 dense-indexer/graph-indexer)" \
    bash -c "svc=\$(docker compose -f '$COMPOSE' config --services); echo \"\$svc\" | grep -vq '^dense-indexer\$' && echo \"\$svc\" | grep -vq '^graph-indexer\$'"
check "deploy compose project name = dify" \
    bash -c "docker compose -f '$COMPOSE' config | grep -E '^name:' | grep -q 'dify'"
check "root shim resolves to deploy compose" \
    docker compose -f "$DIR/docker-compose.yml" config -q

# 下面的调用需要镜像已构建；默认跳过以避免 CI 场景下触发大文件 pull。
if [[ "${INDEXER_RUN_HELP:-0}" = "1" ]]; then
    check "dense-indexer --help" \
        docker compose -f "$COMPOSE" --profile indexer run --rm dense-indexer --help
    check "graph-indexer --help" \
        docker compose -f "$COMPOSE" --profile indexer run --rm graph-indexer --help
fi

exit "$fail"
