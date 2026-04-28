#!/usr/bin/env bash
# Host-based Zoekt indexing for AOSP repo-managed projects.
#
# Iterates .repo/project.list and runs zoekt-git-index on the host
# (no Docker, no zoekt-repo-index) for each sub-project. Produces one
# .zoekt shard per sub-project.
#
# Multi-AOSP same-repo handling:
#   Different AOSP projects often share sub-repos (e.g. external/openssl).
#   To keep their shards from colliding in the shared index dir, we pass
#   -shard_prefix_override "${PROJECT}_" so each project's shards are
#   filesystem-namespaced by project name.
#
# Usage:
#   ./scripts/indexing/sparse/reindex_host.sh                     # all projects
#   ./scripts/indexing/sparse/reindex_host.sh --project t2        # single AOSP project
#   ./scripts/indexing/sparse/reindex_host.sh --parallelism 8     # 8 concurrent indexers
#
# Environment variables:
#   INDEXING_DRY_RUN=1         Skip actual zoekt-git-index (print commands only)
#   PROJECTS_CONFIG_PATH       Override config/projects.yaml path
#   ZOEKT_GIT_INDEX_BIN        Override zoekt-git-index binary path

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
_ZOEKT_BIN="${ZOEKT_GIT_INDEX_BIN:-zoekt-git-index}"

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
# Sanity: zoekt-git-index must be on PATH (or overridden via env)
# ---------------------------------------------------------------------------
if ! command -v "$_ZOEKT_BIN" >/dev/null 2>&1; then
    echo "Error: '$_ZOEKT_BIN' not found on PATH." >&2
    echo "  Install with: go install github.com/sourcegraph/zoekt/cmd/zoekt-git-index@latest" >&2
    echo "  Or set ZOEKT_GIT_INDEX_BIN to point at the binary." >&2
    exit 127
fi

# ---------------------------------------------------------------------------
# Python config helper
# ---------------------------------------------------------------------------
_PYHELPER="$(dirname "$0")/../_project_config.py"

_get_project_config() {
    local config_block
    config_block=$(python3 "$_PYHELPER" --project "$1")
    eval "$config_block"
}

# ---------------------------------------------------------------------------
# _index_one_sub  source_root  index_dir  sub_path  project_name  counter  total  status_dir
#   Run zoekt-git-index for one sub-project. Designed for background execution.
# ---------------------------------------------------------------------------
_index_one_sub() {
    # Disarm inherited EXIT trap from _indexing_lib.sh so background
    # subshells don't call finish_indexing_job on exit.
    trap - EXIT

    local source_root="$1" index_dir="$2" sub_path="$3"
    local project_name="$4" counter="$5" total="$6" status_dir="$7"
    local worktree="${source_root}/${sub_path}"

    if [[ ! -d "$worktree" ]] || [[ ! -e "${worktree}/.git" ]]; then
        echo "[${project_name}][${counter}/${total}] SKIP ${sub_path} (no .git)" >&2
        return 0
    fi

    echo "[${project_name}][${counter}/${total}] Indexing ${sub_path}" >&2

    # Build a per-sub-repo shard prefix: <project>_<sub_path with / -> _>
    # -shard_prefix_override REPLACES the entire prefix (it doesn't prepend),
    # so we must encode the sub-repo identity here too — otherwise every
    # sub-repo writes to the same filename and overwrites the previous one.
    local sub_slug="${sub_path//\//_}"
    local shard_prefix="${project_name}_${sub_slug}"

    if [[ "${INDEXING_DRY_RUN:-0}" == "1" ]]; then
        echo "[dry-run] $_ZOEKT_BIN -index ${index_dir} -shard_prefix_override ${shard_prefix} ${worktree}" >&2
        return 0
    fi

    # Per-project + per-sub-repo namespacing: two AOSPs sharing the same
    # sub-repo (e.g. external/openssl) and two sub-repos in one AOSP both
    # land in distinct shard files in the shared index dir.
    if ! "$_ZOEKT_BIN" \
        -index "$index_dir" \
        -shard_prefix_override "$shard_prefix" \
        "$worktree" 2>&1; then
        echo "[${project_name}][${counter}/${total}] FAILED ${sub_path}" >&2
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
        wait -n 2>/dev/null || true
    done
}

# ---------------------------------------------------------------------------
# _index_project  project_name
# ---------------------------------------------------------------------------
_index_project() {
    local project_name="$1"

    local NAME REPO_PATH INDEX_DIR ZOEKT_URL SHARED_INDEX_DIR
    _get_project_config "$project_name"

    local source_root
    source_root="$(dirname "$REPO_PATH")"

    local project_list="${REPO_PATH}/project.list"
    if [[ ! -f "$project_list" ]]; then
        echo "Error: project.list not found at ${project_list}" >&2
        return 1
    fi

    local index_dir="${SHARED_INDEX_DIR:-$INDEX_DIR}"
    mkdir -p "$index_dir"

    local total
    total=$(wc -l < "$project_list")
    info "Project '${NAME}': ${total} sub-projects, parallelism=${_PARALLELISM}, bin=${_ZOEKT_BIN}"
    info "Source: ${source_root}  Index: ${index_dir}"

    start_indexing_job "$REPO_PATH" zoekt "$NAME"

    local start_time
    start_time=$(date +%s)

    local status_dir
    status_dir=$(mktemp -d)

    local counter=0
    while IFS= read -r sub_path; do
        [[ -z "$sub_path" ]] && continue
        counter=$((counter + 1))

        if [[ "$_PARALLELISM" -le 1 ]]; then
            _index_one_sub "$source_root" "$index_dir" "$sub_path" "$NAME" "$counter" "$total" "$status_dir" || true
        else
            _wait_for_slot "$_PARALLELISM"
            _index_one_sub "$source_root" "$index_dir" "$sub_path" "$NAME" "$counter" "$total" "$status_dir" &
        fi
    done < "$project_list"

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
    info "Host indexing complete: $(date)"
    exit "$_overall"
fi

info "Host indexing complete: $(date)"
