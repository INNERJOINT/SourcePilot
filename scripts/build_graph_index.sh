#!/usr/bin/env bash
# 图谱索引构建 — 通过 docker compose 调起 graph-indexer 容器
#
# 用法:
#   ./scripts/build_graph_index.sh [--source-root /src/frameworks/base] \
#       [--languages java,cpp,python] [--max-files 500] [--reset] [--strict] [其他参数]
#
# 说明:
#   - 若未传 --source-root，默认注入 --source-root /src（即挂进容器的 AOSP_SOURCE_ROOT 根）。
#   - 若传入宿主机绝对路径并落在 $AOSP_SOURCE_ROOT 下，会自动翻译为 /src/<subpath>；
#     否则保持原样（允许用户直接给 /src/... 的容器内路径）。
set -euo pipefail

DIR=$(cd "$(dirname "$0")/.." && pwd)           # 项目根
GRAPH_DIR="$DIR/deploy/graph"
COMPOSE_FILE="$DIR/deploy/docker-compose.yml"

# shellcheck source=./_indexing_lib.sh
source "$(dirname "$0")/_indexing_lib.sh"

for envfile in "$DIR/.env" "$GRAPH_DIR/.env"; do
    if [ -f "$envfile" ]; then
        set -a
        # shellcheck disable=SC1090
        source "$envfile"
        set +a
    fi
done

AOSP_SOURCE_ROOT="${AOSP_SOURCE_ROOT:-/mnt/code/ACE}"
AOSP_SOURCE_ROOT="${AOSP_SOURCE_ROOT%/}"

translate_path() {
    local host_path="$1"
    host_path="${host_path%/}"
    if [[ "$host_path" == /src* ]]; then
        # 已经是容器内路径
        echo "$host_path"
    elif [[ "$host_path" == "$AOSP_SOURCE_ROOT" ]]; then
        echo "/src"
    elif [[ "$host_path" == "$AOSP_SOURCE_ROOT"/* ]]; then
        echo "/src/${host_path#${AOSP_SOURCE_ROOT}/}"
    else
        echo "ERROR: --source-root '$host_path' 不在 AOSP_SOURCE_ROOT='$AOSP_SOURCE_ROOT' 之下" >&2
        return 2
    fi
}

ARGS=()
HAS_SOURCE_ROOT=false
i=0
argv=("$@")
n=$#
while (( i < n )); do
    arg="${argv[$i]}"
    case "$arg" in
        --source-root)
            host_path="${argv[$((i+1))]:-}"
            if [[ -z "$host_path" ]]; then
                echo "ERROR: --source-root 需要一个参数" >&2
                exit 2
            fi
            container_path=$(translate_path "$host_path") || exit 2
            ARGS+=("--source-root" "$container_path")
            HAS_SOURCE_ROOT=true
            i=$((i+2))
            ;;
        --source-root=*)
            host_path="${arg#--source-root=}"
            container_path=$(translate_path "$host_path") || exit 2
            ARGS+=("--source-root=$container_path")
            HAS_SOURCE_ROOT=true
            i=$((i+1))
            ;;
        *)
            ARGS+=("$arg")
            i=$((i+1))
            ;;
    esac
done

if ! $HAS_SOURCE_ROOT; then
    ARGS=("--source-root" "/src" "${ARGS[@]}")
fi

echo "[graph-indexer] AOSP_SOURCE_ROOT=$AOSP_SOURCE_ROOT  ARGS=${ARGS[*]}"

# Determine repo label for job tracking (use source-root arg or default /src)
_GRAPH_REPO_LABEL="${AOSP_SOURCE_ROOT}"
for _a in "${ARGS[@]}"; do
    case "$_a" in /src*) _GRAPH_REPO_LABEL="$_a"; break ;; esac
done
start_indexing_job "$_GRAPH_REPO_LABEL" graph

if [[ "${INDEXING_DRY_RUN:-0}" == "1" ]]; then
    echo "[graph-indexer] DRY_RUN — skipping docker compose"
    trap - EXIT
    finish_indexing_job success 0
    exit 0
fi

docker compose \
    -f "$COMPOSE_FILE" \
    --profile indexer \
    run --rm graph-indexer "${ARGS[@]}" 2>&1 | tee -a "${LOG_PATH:-/dev/stderr}"
_graph_exit=${PIPESTATUS[0]}
trap - EXIT
finish_indexing_job "$([ "$_graph_exit" -eq 0 ] && echo success || echo fail)" "$_graph_exit"
exit "$_graph_exit"
