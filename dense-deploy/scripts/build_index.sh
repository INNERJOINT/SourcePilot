#!/usr/bin/env bash
# 向量索引构建 — 通过 docker compose 调起 dense-indexer 容器
#
# 用法:
#   ./dense-deploy/scripts/build_index.sh \
#       --source-dir /mnt/code/ACE/frameworks/base \
#       --repo-name frameworks/base \
#       [--batch-size 32] [其他 build_dense_index.py 参数]
#
# 行为:
#   - 在宿主机不再直接运行 Python；改走容器 dense-indexer。
#   - 本脚本负责把 --source-dir 的宿主机绝对路径翻译为 /src/<subpath>，
#     前提是它落在 $AOSP_SOURCE_ROOT 之下（与 compose 的 :ro 卷一致）。
#
# 前置:
#   - Milvus + embedding-server 已通过 `docker compose up -d` 启动并 healthy。
#   - .env 中设置了 AOSP_SOURCE_ROOT（或使用默认 /mnt/code/ACE）。
set -euo pipefail

DIR=$(cd "$(dirname "$0")/.." && pwd)
PROJ_ROOT=$(cd "$DIR/.." && pwd)

# 加载 .env（项目根优先，dense-deploy 覆盖）
for envfile in "$PROJ_ROOT/.env" "$DIR/.env"; do
    if [ -f "$envfile" ]; then
        set -a
        # shellcheck disable=SC1090
        source "$envfile"
        set +a
    fi
done

AOSP_SOURCE_ROOT="${AOSP_SOURCE_ROOT:-/mnt/code/ACE}"
AOSP_SOURCE_ROOT="${AOSP_SOURCE_ROOT%/}"

# 把 --source-dir <host-abs-path> 透明翻译为 --source-dir /src/<rel-path>。
# 其他参数原样透传；若未提供 --source-dir 则无操作（供 --help 等场景使用）。
ARGS=()
i=0
argv=("$@")
n=$#
while (( i < n )); do
    arg="${argv[$i]}"
    case "$arg" in
        --source-dir)
            host_path="${argv[$((i+1))]:-}"
            if [[ -z "$host_path" ]]; then
                echo "ERROR: --source-dir 需要一个参数" >&2
                exit 2
            fi
            # 规范化宿主机路径（去尾斜杠）
            host_path="${host_path%/}"
            if [[ "$host_path" == "$AOSP_SOURCE_ROOT" ]]; then
                container_path="/src"
            elif [[ "$host_path" == "$AOSP_SOURCE_ROOT"/* ]]; then
                container_path="/src/${host_path#${AOSP_SOURCE_ROOT}/}"
            else
                echo "ERROR: --source-dir '$host_path' 不在 AOSP_SOURCE_ROOT='$AOSP_SOURCE_ROOT' 之下" >&2
                echo "       请调整 .env 中的 AOSP_SOURCE_ROOT 或传入 \$AOSP_SOURCE_ROOT 之下的路径。" >&2
                exit 2
            fi
            ARGS+=("--source-dir" "$container_path")
            i=$((i+2))
            ;;
        --source-dir=*)
            host_path="${arg#--source-dir=}"
            host_path="${host_path%/}"
            if [[ "$host_path" == "$AOSP_SOURCE_ROOT" ]]; then
                container_path="/src"
            elif [[ "$host_path" == "$AOSP_SOURCE_ROOT"/* ]]; then
                container_path="/src/${host_path#${AOSP_SOURCE_ROOT}/}"
            else
                echo "ERROR: --source-dir '$host_path' 不在 AOSP_SOURCE_ROOT='$AOSP_SOURCE_ROOT' 之下" >&2
                exit 2
            fi
            ARGS+=("--source-dir=$container_path")
            i=$((i+1))
            ;;
        *)
            ARGS+=("$arg")
            i=$((i+1))
            ;;
    esac
done

echo "[dense-indexer] AOSP_SOURCE_ROOT=$AOSP_SOURCE_ROOT  ARGS=${ARGS[*]:-<none>}"

exec docker compose \
    -f "$DIR/docker-compose.yml" \
    --profile indexer \
    run --rm dense-indexer "${ARGS[@]}"
