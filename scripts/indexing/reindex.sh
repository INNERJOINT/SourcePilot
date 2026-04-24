#!/usr/bin/env bash
# 触发 zoekt 索引重建 (支持多项目)
# 用法:
#   ./scripts/indexing/reindex.sh                    # 索引所有项目 (默认)
#   ./scripts/indexing/reindex.sh --all              # 索引所有项目
#   ./scripts/indexing/reindex.sh --project <name>   # 索引单个项目
#
# 环境变量:
#   INDEXING_DRY_RUN=1   跳过实际索引操作 (用于测试)
#   PROJECTS_CONFIG_PATH 覆盖 config/projects.yaml 路径

set -euo pipefail
DIR=$(cd "$(dirname "$0")/../.." && pwd)
cd "$DIR"

source "$(dirname "$0")/../share/_common.sh"
_common_parse_help "$@"

# shellcheck source=./_indexing_lib.sh
source "$(dirname "$0")/_indexing_lib.sh"

# 加载 .env 配置（如果存在）
if [ -f "$DIR/.env" ]; then
    source "$DIR/scripts/share/_env.sh"
fi

# ---------------------------------------------------------------------------
# Parse --project / --all
# ---------------------------------------------------------------------------
_PROJECT_NAME=""
_MODE="all"  # default: index all projects

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
        *)
            shift
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Helper: index one project (reads NAME/REPO_PATH/INDEX_DIR from env block)
# ---------------------------------------------------------------------------
_index_project() {
    local name="$1"
    local repo_path="$2"
    local index_dir="$3"

    echo "開始索引專案 '$name' (repo: $repo_path, index: $index_dir)..." >&2

    if [ ! -d "$repo_path" ]; then
        echo "Error: 仓库路径不存在: $repo_path" >&2
        return 1
    fi

    start_indexing_job "$repo_path" zoekt "$name"

    if [[ "${INDEXING_DRY_RUN:-0}" == "1" ]]; then
        echo "[reindex] DRY_RUN — skipping zoekt-git-index for project '$name'"
        trap - EXIT
        finish_indexing_job success 0
        echo "索引完成(dry-run) 專案 '$name': $(date)" >&2
        return 0
    fi

    mkdir -p "$index_dir"
    zoekt-git-index -index "$index_dir" "$repo_path" 2>&1 | tee -a "${LOG_PATH:-/dev/stderr}"
    local _exit=${PIPESTATUS[0]}
    trap - EXIT
    finish_indexing_job "$([ "$_exit" -eq 0 ] && echo success || echo fail)" "$_exit"
    echo "索引完成 專案 '$name': $(date)" >&2
    return "$_exit"
}

# ---------------------------------------------------------------------------
# Helper: eval output from _project_config.py then call _index_project
# ---------------------------------------------------------------------------
_PYHELPER="$(dirname "$0")/_project_config.py"

_run_project_from_config() {
    local config_block
    config_block=$(python3 "$_PYHELPER" --project "$1")
    # Parse shell-eval-safe lines (NAME='...' REPO_PATH='...' etc.)
    local NAME REPO_PATH INDEX_DIR ZOEKT_URL
    eval "$config_block"
    _index_project "$NAME" "$REPO_PATH" "$INDEX_DIR"
}

_run_all_projects_from_config() {
    local names
    names=$(python3 "$_PYHELPER" --list)
    local _overall=0
    while IFS= read -r name; do
        [[ -z "$name" ]] && continue
        _run_project_from_config "$name" || _overall=$?
    done <<< "$names"
    return "$_overall"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if [[ "$_MODE" == "single" ]]; then
    _run_project_from_config "$_PROJECT_NAME"
else
    _run_all_projects_from_config
fi

echo "全部索引重建完成: $(date)" >&2
