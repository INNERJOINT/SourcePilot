#!/usr/bin/env bash
# 批量构建 dense 向量索引 — 索引 frameworks/ 和 packages/ 下所有仓库
#
# 用法:
#   ./scripts/build_dense_index_batch.sh [--aosp-root /mnt/code/ACE] [--skip-existing]
#
# 新数据追加到已有 Milvus collection，不影响已索引的仓库。
set -uo pipefail  # 注意：不使用 -e，单个 repo 失败时继续处理其余 repo

# shellcheck source=./_indexing_lib.sh
source "$(dirname "$0")/_indexing_lib.sh"

AOSP_ROOT="${AOSP_ROOT:-/mnt/code/ACE}"
SKIP_EXISTING=false
BUILD_SCRIPT="$(cd "$(dirname "$0")/../deploy/dense" && pwd)/scripts/build_index.sh"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --aosp-root) AOSP_ROOT="$2"; shift 2 ;;
        --skip-existing) SKIP_EXISTING=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ ! -x "$BUILD_SCRIPT" ]]; then
    echo "ERROR: build_index.sh not found at $BUILD_SCRIPT"
    exit 1
fi

# 收集要索引的仓库：(source_dir, repo_name)
REPOS=()

# frameworks/* — 每个子目录作为一个 repo
for dir in "$AOSP_ROOT"/frameworks/*/; do
    [[ -d "$dir" ]] || continue
    name=$(basename "$dir")
    REPOS+=("$dir|frameworks/$name")
done

# packages/*/* — 按二级目录索引 (packages/apps/Settings 等)
for category in "$AOSP_ROOT"/packages/*/; do
    [[ -d "$category" ]] || continue
    cat_name=$(basename "$category")
    for dir in "$category"*/; do
        [[ -d "$dir" ]] || continue
        name=$(basename "$dir")
        REPOS+=("$dir|packages/$cat_name/$name")
    done
done

echo "Found ${#REPOS[@]} repos to index under $AOSP_ROOT"
echo ""

SUCCEEDED=0
FAILED=0
SKIPPED=0

for entry in "${REPOS[@]}"; do
    source_dir="${entry%%|*}"
    repo_name="${entry##*|}"

    # 快速检查：目录下有没有源码文件
    file_count=$(find "$source_dir" -maxdepth 5 -type f \( -name "*.java" -o -name "*.kt" -o -name "*.cpp" -o -name "*.c" -o -name "*.h" -o -name "*.aidl" -o -name "*.go" -o -name "*.rs" -o -name "*.py" \) -print -quit 2>/dev/null | wc -l)
    if [[ "$file_count" -eq 0 ]]; then
        echo "SKIP  $repo_name (no source files)"
        ((SKIPPED++))
        continue
    fi

    echo "===== INDEX  $repo_name ====="
    start_indexing_job "$repo_name" dense
    job_exit=0
    if [[ "${INDEXING_DRY_RUN:-0}" == "1" ]]; then
        echo "DRY_RUN  $repo_name (skipping docker)"
    elif "$BUILD_SCRIPT" --source-dir "$source_dir" --repo-name "$repo_name" 2>&1 | tee -a "${LOG_PATH:-/dev/stderr}"; then
        : # success — handled below
    else
        job_exit=$?
    fi
    if [[ $job_exit -eq 0 ]]; then
        finish_indexing_job success 0
        ((SUCCEEDED++))
        echo "DONE  $repo_name"
    else
        finish_indexing_job fail $job_exit
        ((FAILED++))
        echo "FAIL  $repo_name"
    fi
    echo ""
done

echo "==============================="
echo "Total: ${#REPOS[@]}  Succeeded: $SUCCEEDED  Failed: $FAILED  Skipped: $SKIPPED"
