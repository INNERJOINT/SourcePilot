#!/usr/bin/env bash
# Docker-based Zoekt indexing for AOSP repo-managed projects.
#
# Iterates .repo/project.list and runs zoekt-git-index inside a Docker
# container for each sub-project.  Produces one .zoekt shard per sub-project.
#
# Usage:
#   ./scripts/indexing/sparse/reindex_docker.sh                        # all projects (default)
#   ./scripts/indexing/sparse/reindex_docker.sh --project t2            # single AOSP project
#   ./scripts/indexing/sparse/reindex_docker.sh --parallelism 8         # 8 concurrent containers
#
# Environment variables:
#   INDEXING_DRY_RUN=1         Skip actual docker run (print commands only)
#   PROJECTS_CONFIG_PATH       Override config/projects.yaml path
#   ZOEKT_DOCKER_IMAGE         Override Docker image (default: dify-sparse-index-zoekt:latest)

set -euo pipefail
DIR=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$DIR"

source "$(dirname "$0")/../../share/_common.sh"
_common_parse_help "$@"

# shellcheck source=../_indexing_lib.sh
source "$(dirname "$0")/../_indexing_lib.sh"

if [ -f "$DIR/.env" ]; then
    # shellcheck source=/dev/null
    source "$DIR/scripts/share/_env.sh"
fi

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_PROJECT_NAME=""
_MODE="all"
_PARALLELISM=4
_DOCKER_IMAGE="${ZOEKT_DOCKER_IMAGE:-dify-sparse-index-zoekt:latest}"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)
            shift
            _PROJECT_NAME="${1:?--project requires a name}"
            _MODE="single"
            shift
            ;;
        --all)
            _MODE="all"
            shift
            ;;
        --parallelism)
            shift
            _PARALLELISM="${1:?--parallelism requires a number}"
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Python config helper
# ---------------------------------------------------------------------------
_PYHELPER="$(dirname "$0")/_project_config.py"

_get_project_config() {
    local config_block
    config_block=$(python3 "$_PYHELPER" --project "$1")
    eval "$config_block"
}

# ---------------------------------------------------------------------------
# _index_one_sub  source_root  index_dir  sub_path  counter  total
#   Runs zoekt-git-index in Docker for one sub-project.
#   Designed to run as a background job — writes status to a temp dir.
# ---------------------------------------------------------------------------
_index_one_sub() {
    # Disarm inherited EXIT trap from _indexing_lib.sh so background
    # subshells don't call finish_indexing_job on exit.
    trap - EXIT

    local source_root="$1" index_dir="$2" sub_path="$3"
    local counter="$4" total="$5" status_dir="$6"
    local worktree="${source_root}/${sub_path}"

    if [[ ! -d "$worktree" ]] || [[ ! -e "${worktree}/.git" ]]; then
        echo "[${counter}/${total}] SKIP ${sub_path}" >&2
        return 0
    fi

    echo "[${counter}/${total}] Indexing ${sub_path}" >&2

    if [[ "${INDEXING_DRY_RUN:-0}" == "1" ]]; then
        echo "[dry-run] docker run --rm -v ${source_root}:/src:ro -v ${index_dir}:/idx ${_DOCKER_IMAGE} zoekt-git-index -index /idx /src/${sub_path}" >&2
        return 0
    fi

    if ! docker run --rm \
        -v "${source_root}:/src:ro" \
        -v "${index_dir}:/idx" \
        "${_DOCKER_IMAGE}" \
        zoekt-git-index -index /idx "/src/${sub_path}" 2>&1; then
        echo "[${counter}/${total}] FAILED ${sub_path}" >&2
        touch "${status_dir}/fail.${counter}"
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# _wait_for_slot  max_jobs
#   Block until background job count drops below max_jobs.
# ---------------------------------------------------------------------------
_wait_for_slot() {
    local max_jobs="$1"
    while true; do
        local running
        running=$(jobs -rp | wc -l)
        if [[ "$running" -lt "$max_jobs" ]]; then
            break
        fi
        # Wait for any one job to finish
        wait -n 2>/dev/null || true
    done
}

# ---------------------------------------------------------------------------
# _index_project  project_name
# ---------------------------------------------------------------------------
_index_project() {
    local project_name="$1"

    local NAME REPO_PATH INDEX_DIR ZOEKT_URL
    _get_project_config "$project_name"

    local source_root
    source_root="$(dirname "$REPO_PATH")"

    local project_list="${REPO_PATH}/project.list"
    if [[ ! -f "$project_list" ]]; then
        die "project.list not found at ${project_list}"
    fi

    mkdir -p "$INDEX_DIR"

    local total
    total=$(wc -l < "$project_list")
    info "Project '${NAME}': ${total} sub-projects, parallelism=${_PARALLELISM}, image=${_DOCKER_IMAGE}"
    info "Source: ${source_root}  Index: ${INDEX_DIR}"

    start_indexing_job "$REPO_PATH" zoekt "$NAME"

    local start_time
    start_time=$(date +%s)

    # Temp dir for failure markers
    local status_dir
    status_dir=$(mktemp -d)

    local counter=0
    while IFS= read -r sub_path; do
        [[ -z "$sub_path" ]] && continue
        counter=$((counter + 1))

        if [[ "$_PARALLELISM" -le 1 ]]; then
            _index_one_sub "$source_root" "$INDEX_DIR" "$sub_path" "$counter" "$total" "$status_dir" || true
        else
            _wait_for_slot "$_PARALLELISM"
            _index_one_sub "$source_root" "$INDEX_DIR" "$sub_path" "$counter" "$total" "$status_dir" &
        fi
    done < "$project_list"

    # Wait for remaining background jobs
    wait 2>/dev/null || true

    local fail_count
    fail_count=$(find "$status_dir" -name 'fail.*' 2>/dev/null | wc -l)
    rm -rf "$status_dir"

    trap - EXIT
    local status="success"
    if [[ "$fail_count" -gt 0 ]]; then
        status="fail"
    fi
    finish_indexing_job "$status" "$fail_count"

    local end_time elapsed
    end_time=$(date +%s)
    elapsed=$((end_time - start_time))

    info "=== Summary for '${NAME}' ==="
    info "Total: ${total}, Failed: ${fail_count}, Elapsed: ${elapsed}s"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if [[ "$_MODE" == "single" ]]; then
    _index_project "$_PROJECT_NAME"
else
    _names=$(python3 "$_PYHELPER" --list)
    _overall=0
    while IFS= read -r name; do
        [[ -z "$name" ]] && continue
        _index_project "$name" || _overall=$?
    done <<< "$_names"
    info "Docker indexing complete: $(date)"
    exit "$_overall"
fi

info "Docker indexing complete: $(date)"
