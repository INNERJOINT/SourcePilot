#!/usr/bin/env bash
# 验证 dense-indexer / graph-indexer compose 定义合法，
# 且（如果 docker 可用）容器 --help 可以正常退出。
#
# 用法: ./scripts/verify_indexer_containers.sh
set -uo pipefail

DIR=$(cd "$(dirname "$0")/.." && pwd)
DENSE_COMPOSE="$DIR/dense-deploy/docker-compose.yml"
GRAPH_COMPOSE="$DIR/graph-deploy/docker-compose.yml"
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

check "dense-deploy compose config (profile=indexer)" \
    docker compose -f "$DENSE_COMPOSE" --profile indexer config -q
check "graph-deploy compose config (profile=indexer)" \
    docker compose -f "$GRAPH_COMPOSE" --profile indexer config -q
check "dense-deploy compose config (default profile — 不应含 indexer)" \
    bash -c "docker compose -f '$DENSE_COMPOSE' config --services | grep -vq '^dense-indexer$'"
check "graph-deploy compose config (default profile — 不应含 indexer)" \
    bash -c "docker compose -f '$GRAPH_COMPOSE' config --services | grep -vq '^graph-indexer$'"

# 下面的调用需要镜像已构建；默认跳过以避免 CI 场景下触发大文件 pull。
if [[ "${INDEXER_RUN_HELP:-0}" = "1" ]]; then
    check "dense-indexer --help" \
        docker compose -f "$DENSE_COMPOSE" --profile indexer run --rm dense-indexer --help
    check "graph-indexer --help" \
        docker compose -f "$GRAPH_COMPOSE" --profile indexer run --rm graph-indexer --help
fi

exit "$fail"
