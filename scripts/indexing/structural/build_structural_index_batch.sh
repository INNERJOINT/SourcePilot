#!/usr/bin/env bash
# Batch structural index builder — iterate projects from canonical project_config.py output
#
# Usage:
#   ./scripts/indexing/build_structural_index_batch.sh [extra args passed to build_structural_index.sh]
#
# NOTE: -e intentionally omitted — batch-continue contract: single project failure
# must not abort remaining projects.
set -uo pipefail

# shellcheck source=../_indexing_lib.sh
source "$(dirname "$0")/../_indexing_lib.sh"
# shellcheck source=../../share/_common.sh
source "$(dirname "$0")/../../share/_common.sh"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_SCRIPT="$SCRIPT_DIR/build_structural_index.sh"

_emit_structural_project_lines() {
    python3 - "$SCRIPT_DIR/../project_config.py" <<'PYEOF'
import json
import subprocess
import sys

config_script = sys.argv[1]
payload = json.loads(
    subprocess.check_output(
        [sys.executable, config_script, "--backend", "structural", "--format", "json"],
        text=True,
    )
)
for project in payload.get("projects", []):
    print(
        "\t".join(
            [
                "P",
                project["name"],
                project["source_root"],
                project["mode"],
            ]
        )
    )
    for include in project.get("includes", []):
        print("\t".join(["I", include["source_dir"], include["repo_name"]]))
    print("E")
PYEOF
}

_USER_ARGS=()
_RESET_REQUESTED=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            _common_parse_help --help
            ;;
        --reset)
            _RESET_REQUESTED=true
            shift
            ;;
        --source-root|--project-name|--repo-name)
            echo "ERROR: $1 is managed by build_structural_index_batch.sh" >&2
            exit 2
            ;;
        --source-root=*|--project-name=*|--repo-name=*)
            echo "ERROR: ${1%%=*} is managed by build_structural_index_batch.sh" >&2
            exit 2
            ;;
        *)
            _USER_ARGS+=("$1")
            shift
            ;;
    esac
done

SUCCEEDED=0
FAILED=0
SKIPPED=0

CONFIG_LINES=()
if ! mapfile -t CONFIG_LINES < <(_emit_structural_project_lines); then
    echo "ERROR: failed to load structural backend project config" >&2
    exit 1
fi

line_index=0
while (( line_index < ${#CONFIG_LINES[@]} )); do
    header_line="${CONFIG_LINES[$line_index]}"
    ((line_index += 1))

    IFS=$'\t' read -r rec_type proj_name proj_root proj_mode <<< "$header_line"
    if [[ "$rec_type" != "P" ]]; then
        echo "ERROR: invalid project config record: $header_line" >&2
        exit 1
    fi

    PROJECT_INCLUDES=()
    while (( line_index < ${#CONFIG_LINES[@]} )); do
        row="${CONFIG_LINES[$line_index]}"
        ((line_index += 1))

        IFS=$'\t' read -r row_type col1 col2 <<< "$row"
        if [[ "$row_type" == "E" ]]; then
            break
        fi
        if [[ "$row_type" != "I" ]]; then
            echo "ERROR: invalid include record: $row" >&2
            exit 1
        fi
        PROJECT_INCLUDES+=("$col1|$col2")
    done

    echo "===== STRUCTURAL INDEX: project=$proj_name root=$proj_root mode=$proj_mode ====="
    export AOSP_SOURCE_ROOT="$proj_root"

    case "$proj_mode" in
        disabled)
            echo "SKIP PROJECT  $proj_name (structural mode=disabled)"
            echo ""
            SKIPPED=$((SKIPPED + 1))
            continue
            ;;
        default)
            project_cmd=(
                "$BUILD_SCRIPT"
                --project-name "$proj_name"
                --source-root "$proj_root"
                "${_USER_ARGS[@]}"
            )
            if $_RESET_REQUESTED; then
                project_cmd+=(--reset)
            fi

            if [[ "${INDEXING_DRY_RUN:-0}" == "1" ]]; then
                echo "DRY_RUN  $proj_name"
                echo "DRY_RUN_CMD  ${project_cmd[*]}"
                SUCCEEDED=$((SUCCEEDED + 1))
            elif "${project_cmd[@]}"; then
                SUCCEEDED=$((SUCCEEDED + 1))
                echo "DONE  $proj_name"
            else
                job_exit=$?
                FAILED=$((FAILED + 1))
                echo "FAIL  $proj_name (exit=$job_exit)"
            fi
            echo ""
            ;;
        legacy|explicit)
            if [[ ${#PROJECT_INCLUDES[@]} -eq 0 ]]; then
                echo "SKIP PROJECT  $proj_name (no structural includes resolved)"
                echo ""
                SKIPPED=$((SKIPPED + 1))
                continue
            fi

            project_failed=false
            reset_pending=$_RESET_REQUESTED
            for entry in "${PROJECT_INCLUDES[@]}"; do
                source_dir="${entry%%|*}"
                repo_name="${entry##*|}"

                include_cmd=(
                    "$BUILD_SCRIPT"
                    --project-name "$proj_name"
                    --source-root "$source_dir"
                    --repo-name "$repo_name"
                    "${_USER_ARGS[@]}"
                )
                if $reset_pending; then
                    include_cmd+=(--reset)
                    reset_pending=false
                fi

                if [[ "${INDEXING_DRY_RUN:-0}" == "1" ]]; then
                    echo "DRY_RUN  $proj_name/$repo_name"
                    echo "DRY_RUN_CMD  ${include_cmd[*]}"
                    continue
                fi

                if "${include_cmd[@]}"; then
                    echo "DONE  $proj_name/$repo_name"
                else
                    job_exit=$?
                    project_failed=true
                    echo "FAIL  $proj_name/$repo_name (exit=$job_exit)"
                    echo "SKIP REMAINING INCLUDES  $proj_name"
                    break
                fi
            done

            if [[ "${INDEXING_DRY_RUN:-0}" == "1" ]]; then
                SUCCEEDED=$((SUCCEEDED + 1))
            elif $project_failed; then
                FAILED=$((FAILED + 1))
            else
                SUCCEEDED=$((SUCCEEDED + 1))
                echo "DONE  $proj_name"
            fi
            echo ""
            ;;
        *)
            echo "ERROR: unknown structural mode '$proj_mode' for project '$proj_name'" >&2
            exit 1
            ;;
    esac
done

echo "==============================="
echo "Structural batch complete: Succeeded=$SUCCEEDED  Failed=$FAILED  Skipped=$SKIPPED"
