#!/usr/bin/env bash
# Vector index build — launches the dense-indexer container via docker compose
#
# Usage:
#   ./deploy/dense/scripts/build_index.sh \
#       --source-dir /opt/aosp/aosp_project/frameworks/base \
#       --repo-name frameworks/base \
#       [--batch-size 32] [other build_dense_index.py arguments]
#
# Behavior:
#   - Python is no longer run directly on the host; the dense-indexer container is used instead.
#   - This script translates the --source-dir host absolute path to /src/<subpath>
#     inside the container, provided it falls under $AOSP_SOURCE_ROOT (matching the
#     compose :ro volume mount).
#
# Prerequisites:
#   - Qdrant + embedding-server started and healthy via `docker compose up -d`.
#   - AOSP_SOURCE_ROOT set in .env (or using the default /opt/aosp/aosp_project).
set -euo pipefail

DIR=$(cd "$(dirname "$0")/.." && pwd)             # deploy/dense
PROJ_ROOT=$(cd "$DIR/../.." && pwd)                # repo root
COMPOSE_FILE="$PROJ_ROOT/deploy/docker-compose.yml"

# Load .env (project root takes precedence, deploy/dense can override); preserve
# any key variables explicitly passed by the caller.
_PRESERVE_ENV_VARS=(
    AOSP_SOURCE_ROOT
    DENSE_ENABLED
    DENSE_COLLECTION_NAME
    DENSE_VECTOR_DB_URL
    DENSE_EMBEDDING_URL
    DENSE_EMBEDDING_MODEL
    DENSE_EMBEDDING_DIM
)
declare -A _PRESERVE_ENV_VALS=()
for _var in "${_PRESERVE_ENV_VARS[@]}"; do
    if [[ -v "$_var" ]]; then
        _PRESERVE_ENV_VALS["$_var"]="${!_var}"
    fi
done
for envfile in "$PROJ_ROOT/.env" "$DIR/.env"; do
    if [ -f "$envfile" ]; then
        set -a
        # shellcheck disable=SC1090
        source "$envfile"
        set +a
    fi
done
for _var in "${!_PRESERVE_ENV_VALS[@]}"; do
    export "$_var=${_PRESERVE_ENV_VALS[$_var]}"
done

AOSP_SOURCE_ROOT="${AOSP_SOURCE_ROOT:-/opt/aosp/aosp_project}"
AOSP_SOURCE_ROOT="${AOSP_SOURCE_ROOT%/}"

# Translate --source-dir <host-abs-path> transparently to --source-dir /src/<rel-path>.
# Other arguments are passed through unchanged; if --source-dir is not provided this
# is a no-op (e.g. for --help invocations).
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
                echo "ERROR: --source-dir requires an argument" >&2
                exit 2
            fi
            # Normalize host path (strip trailing slash)
            host_path="${host_path%/}"
            if [[ "$host_path" == "$AOSP_SOURCE_ROOT" ]]; then
                container_path="/src"
            elif [[ "$host_path" == "$AOSP_SOURCE_ROOT"/* ]]; then
                container_path="/src/${host_path#${AOSP_SOURCE_ROOT}/}"
            else
                echo "ERROR: --source-dir '$host_path' is not under AOSP_SOURCE_ROOT='$AOSP_SOURCE_ROOT'" >&2
                echo "       Adjust AOSP_SOURCE_ROOT in .env or pass a path under \$AOSP_SOURCE_ROOT." >&2
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
                echo "ERROR: --source-dir '$host_path' is not under AOSP_SOURCE_ROOT='$AOSP_SOURCE_ROOT'" >&2
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
    -f "$COMPOSE_FILE" \
    --profile indexer \
    run --rm dense-indexer "${ARGS[@]}"
