#!/usr/bin/env bash
# Batch graph index builder — iterate projects from config/projects.yaml
#
# Usage:
#   ./scripts/indexing/build_graph_index_batch.sh [extra args passed to build_graph_index.sh]
#
# NOTE: -e intentionally omitted — batch-continue contract: single project failure
# must not abort remaining projects.
set -uo pipefail

# shellcheck source=./_indexing_lib.sh
source "$(dirname "$0")/_indexing_lib.sh"
# shellcheck source=../share/_common.sh
source "$(dirname "$0")/../share/_common.sh"
# shellcheck source=./project_config.sh
source "$(dirname "$0")/project_config.sh"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

SUCCEEDED=0
FAILED=0

while IFS='|' read -r proj_name proj_root proj_collection; do
    echo "===== GRAPH INDEX: project=$proj_name root=$proj_root ====="

    if [[ "${INDEXING_DRY_RUN:-0}" == "1" ]]; then
        echo "DRY_RUN  $proj_name"
        SUCCEEDED=$((SUCCEEDED + 1))
        continue
    fi

    job_exit=0
    if "$SCRIPT_DIR/build_graph_index.sh" \
        --project-name "$proj_name" \
        --source-root "$proj_root" \
        "$@"; then
        SUCCEEDED=$((SUCCEEDED + 1))
        echo "DONE  $proj_name"
    else
        job_exit=$?
        FAILED=$((FAILED + 1))
        echo "FAIL  $proj_name (exit=$job_exit)"
    fi
    echo ""
done < <(load_projects)

echo "==============================="
echo "Graph batch complete: Succeeded=$SUCCEEDED  Failed=$FAILED"
