#!/usr/bin/env bash
# Structural index build — via docker compose to launch structural-indexer container
#
# Usage:
#   ./scripts/build_structural_index.sh [--source-root /src/frameworks/base] \
#       [--repo-name frameworks/base] [--languages java,cpp,python] \
#       [--max-files 500] [--reset] [--strict] [other args]
#
# Notes:
#   - If not provided --source-root, defaults to injecting --source-root /src
#     (i.e. mounted in container as the AOSP_SOURCE_ROOT root).
#   - If a host absolute path under $AOSP_SOURCE_ROOT is given, it will be
#     auto-translated to /src/<subpath>; otherwise kept as-is (allows user to
#     pass container-internal paths like /src/...).
#   - Caller-set env vars take precedence over .env.
set -euo pipefail

DOCKER_BIN="${DOCKER_BIN:-docker}"

DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd) # project root
STRUCTURAL_DIR="$DIR/deploy/structural"
COMPOSE_FILE="$DIR/deploy/docker-compose.yml"

# shellcheck source=../_indexing_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../_indexing_lib.sh"
source "$(dirname "${BASH_SOURCE[0]}")/../../share/_common.sh"
SOURCEPILOT_ENV_NO_AUTOLOAD=1 source "$(dirname "${BASH_SOURCE[0]}")/../../share/_env.sh"

# Load .env files without overriding caller-set variables (load_env_file
# exports only variables not already set in the environment).
load_env_file "$DIR/.env" 2> /dev/null || true
load_env_file "$STRUCTURAL_DIR/.env" 2> /dev/null || true

AOSP_SOURCE_ROOT="${AOSP_SOURCE_ROOT:-/opt/aosp/aosp_project}"
AOSP_SOURCE_ROOT="${AOSP_SOURCE_ROOT%/}"

translate_path() {
  local host_path="$1"
  host_path="${host_path%/}"
  if [[ "$host_path" == /src* ]]; then
    # already a container-internal path
    echo "$host_path"
  elif [[ "$host_path" == "$AOSP_SOURCE_ROOT" ]]; then
    echo "/src"
  elif [[ "$host_path" == "$AOSP_SOURCE_ROOT"/* ]]; then
    echo "/src/${host_path#${AOSP_SOURCE_ROOT}/}"
  else
    echo "ERROR: --source-root '$host_path' is not under AOSP_SOURCE_ROOT='$AOSP_SOURCE_ROOT'" >&2
    return 2
  fi
}

main() {
  ARGS=()
  HAS_SOURCE_ROOT=false
  _STRUCTURAL_PROJECT_NAME=""
  _STRUCTURAL_REPO_NAME=""
  _STRUCTURAL_SOURCE_ROOT_LABEL="$AOSP_SOURCE_ROOT"
  local i=0
  local argv=("$@")
  local n=$#
  while ((i < n)); do
    arg="${argv[$i]}"
    case "$arg" in
      -h | --help) _common_parse_help --help ;;
      --source-root)
        host_path="${argv[$((i + 1))]:-}"
        if [[ -z "$host_path" ]]; then
          echo "ERROR: --source-root requires an argument" >&2
          exit 2
        fi
        container_path=$(translate_path "$host_path") || exit 2
        ARGS+=("--source-root" "$container_path")
        HAS_SOURCE_ROOT=true
        _STRUCTURAL_SOURCE_ROOT_LABEL="$container_path"
        i=$((i + 2))
        ;;
      --source-root=*)
        host_path="${arg#--source-root=}"
        container_path=$(translate_path "$host_path") || exit 2
        ARGS+=("--source-root=$container_path")
        HAS_SOURCE_ROOT=true
        _STRUCTURAL_SOURCE_ROOT_LABEL="$container_path"
        i=$((i + 1))
        ;;
      --project-name)
        _STRUCTURAL_PROJECT_NAME="${argv[$((i + 1))]:-}"
        ARGS+=("$arg" "$_STRUCTURAL_PROJECT_NAME")
        i=$((i + 2))
        ;;
      --project-name=*)
        _STRUCTURAL_PROJECT_NAME="${arg#--project-name=}"
        ARGS+=("$arg")
        i=$((i + 1))
        ;;
      --repo-name)
        _STRUCTURAL_REPO_NAME="${argv[$((i + 1))]:-}"
        ARGS+=("$arg" "$_STRUCTURAL_REPO_NAME")
        i=$((i + 2))
        ;;
      --repo-name=*)
        _STRUCTURAL_REPO_NAME="${arg#--repo-name=}"
        ARGS+=("$arg")
        i=$((i + 1))
        ;;
      *)
        ARGS+=("$arg")
        i=$((i + 1))
        ;;
    esac
  done

  if ! $HAS_SOURCE_ROOT; then
    ARGS=("--source-root" "/src" "${ARGS[@]}")
    _STRUCTURAL_SOURCE_ROOT_LABEL="/src"
  fi

  if [[ -n "$_STRUCTURAL_REPO_NAME" ]]; then
    _STRUCTURAL_REPO_LABEL="$_STRUCTURAL_REPO_NAME"
  else
    _STRUCTURAL_REPO_LABEL="$_STRUCTURAL_SOURCE_ROOT_LABEL"
  fi

  echo "[structural-indexer] AOSP_SOURCE_ROOT=$AOSP_SOURCE_ROOT  ARGS=${ARGS[*]}"
  start_indexing_job "$_STRUCTURAL_REPO_LABEL" structural "$_STRUCTURAL_PROJECT_NAME"

  if [[ "${INDEXING_DRY_RUN:-0}" == "1" ]]; then
    echo "[structural-indexer] DRY_RUN — skipping docker compose"
    trap - EXIT
    finish_indexing_job success 0
    exit 0
  fi

  "$DOCKER_BIN" compose \
    -f "$COMPOSE_FILE" \
    --profile indexer \
    run --rm structural-indexer "${ARGS[@]}" 2>&1 | tee -a "${LOG_PATH:-/dev/stderr}"
  _structural_exit=${PIPESTATUS[0]}
  trap - EXIT
  finish_indexing_job "$([ "$_structural_exit" -eq 0 ] && echo success || echo fail)" "$_structural_exit"
  exit "$_structural_exit"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
