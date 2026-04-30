#!/usr/bin/env bash
# Batch build dense vector index — supports multi-project config and backend scope control
#
# Usage:
#   ./scripts/build_dense_index_batch.sh [--skip-existing]
#
# New data appends to existing Qdrant collection, does not affect already-indexed repos.
#
# Environment variables:
#   INDEXING_DRY_RUN=1           Skip actual docker calls (print commands only)
#   INDEXING_SKIP_SOURCE_SCAN=1  Skip find(1) source-file probe; treats every repo as non-empty
#                                 (useful in tests to avoid scanning real AOSP trees)
#
# NOTE: -e intentionally omitted — batch-continue contract: single repo failure
# must not abort remaining repos.
set -uo pipefail

# shellcheck source=../_indexing_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../_indexing_lib.sh"
source "$(dirname "${BASH_SOURCE[0]}")/../../share/_common.sh"

# shellcheck disable=SC2034  # SKIP_EXISTING parsed but reserved for future use
SKIP_EXISTING=false
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_SCRIPT="${BUILD_SCRIPT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../deploy/dense" 2> /dev/null && pwd)/scripts/build_index.sh}"

# _enumerate_default_repos AOSP_ROOT
#   Prints "dir|repo_name" lines for frameworks/* and packages/*/* repos.
#   Pure: no side-effects, no globals written. Exposed for unit tests via sourcing.
_enumerate_default_repos() {
  local aosp_root="$1"
  for dir in "$aosp_root"/frameworks/*/; do
    [[ -d "$dir" ]] || continue
    local name
    name=$(basename "$dir")
    echo "${dir}|frameworks/${name}"
  done
  for category in "$aosp_root"/packages/*/; do
    [[ -d "$category" ]] || continue
    local cat_name
    cat_name=$(basename "$category")
    for dir in "$category"*/; do
      [[ -d "$dir" ]] || continue
      local name
      name=$(basename "$dir")
      echo "${dir}|packages/${cat_name}/${name}"
    done
  done
}

# _parse_dense_config_lines
#   Reads CONFIG_LINES array (must be set in caller scope) and populates:
#     PROJECT_HEADERS           — array of "name<TAB>root<TAB>collection<TAB>mode"
#     PROJECT_INCLUDES_BY_NAME  — assoc array; value is newline-separated "dir|name" pairs
#   Pure: only reads CONFIG_LINES, writes the two output arrays. Exposed for tests.
_parse_dense_config_lines() {
  PROJECT_HEADERS=()
  declare -gA PROJECT_INCLUDES_BY_NAME=()

  local line_index=0
  while ((line_index < ${#CONFIG_LINES[@]})); do
    local header_line="${CONFIG_LINES[$line_index]}"
    ((line_index += 1))

    local rec_type proj_name proj_root proj_collection proj_mode
    IFS=$'\t' read -r rec_type proj_name proj_root proj_collection proj_mode <<< "$header_line"
    if [[ "$rec_type" != "P" ]]; then
      echo "ERROR: invalid project config record: $header_line" >&2
      return 1
    fi

    PROJECT_HEADERS+=("${proj_name}"$'\t'"${proj_root}"$'\t'"${proj_collection}"$'\t'"${proj_mode}")

    local includes=""
    while ((line_index < ${#CONFIG_LINES[@]})); do
      local row="${CONFIG_LINES[$line_index]}"
      ((line_index += 1))

      local row_type col1 col2
      IFS=$'\t' read -r row_type col1 col2 <<< "$row"
      if [[ "$row_type" == "E" ]]; then
        break
      fi
      if [[ "$row_type" != "I" ]]; then
        echo "ERROR: invalid include record: $row" >&2
        return 1
      fi
      if [[ -n "$includes" ]]; then
        includes+=$'\n'
      fi
      includes+="${col1}|${col2}"
    done
    PROJECT_INCLUDES_BY_NAME["$proj_name"]="$includes"
  done
}

_emit_dense_project_lines() {
  "${PYTHON_BIN:-python3}" - "$SCRIPT_DIR/../project_config.py" << 'PYEOF'
import json
import subprocess
import sys

config_script = sys.argv[1]
payload = json.loads(
    subprocess.check_output(
        [sys.executable, config_script, "--backend", "dense", "--format", "json"],
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
                project["collection_name"],
                project["mode"],
            ]
        )
    )
    for include in project.get("includes", []):
        print("\t".join(["I", include["source_dir"], include["repo_name"]]))
    print("E")
PYEOF
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -h | --help) _common_parse_help --help ;;
      --skip-existing)
        # shellcheck disable=SC2034  # reserved for future skip feature
        SKIP_EXISTING=true
        shift
        ;;
      *)
        echo "Unknown option: $1"
        exit 1
        ;;
    esac
  done

  if [[ ! -x "$BUILD_SCRIPT" ]] && [[ "${INDEXING_DRY_RUN:-0}" != "1" ]]; then
    echo "ERROR: build_index.sh not found at $BUILD_SCRIPT"
    exit 1
  fi

  TOTAL_SUCCEEDED=0
  TOTAL_FAILED=0
  TOTAL_SKIPPED=0

  CONFIG_LINES=()
  if ! mapfile -t CONFIG_LINES < <(_emit_dense_project_lines); then
    echo "ERROR: failed to load dense backend project config" >&2
    exit 1
  fi

  line_index=0
  while ((line_index < ${#CONFIG_LINES[@]})); do
    header_line="${CONFIG_LINES[$line_index]}"
    ((line_index += 1))

    IFS=$'\t' read -r rec_type proj_name proj_root proj_collection proj_mode <<< "$header_line"
    if [[ "$rec_type" != "P" ]]; then
      echo "ERROR: invalid project config record: $header_line" >&2
      exit 1
    fi

    PROJECT_INCLUDES=()
    while ((line_index < ${#CONFIG_LINES[@]})); do
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

    echo "===== PROJECT: $proj_name (root=$proj_root, collection=$proj_collection, mode=$proj_mode) ====="
    AOSP_ROOT="$proj_root"
    export AOSP_SOURCE_ROOT="$AOSP_ROOT"
    export DENSE_COLLECTION_NAME="$proj_collection"

    REPOS=()
    case "$proj_mode" in
      disabled)
        echo "SKIP PROJECT  $proj_name (dense mode=disabled)"
        echo ""
        continue
        ;;
      default)
        for dir in "$AOSP_ROOT"/frameworks/*/; do
          [[ -d "$dir" ]] || continue
          name=$(basename "$dir")
          REPOS+=("$dir|frameworks/$name")
        done

        for category in "$AOSP_ROOT"/packages/*/; do
          [[ -d "$category" ]] || continue
          cat_name=$(basename "$category")
          for dir in "$category"*/; do
            [[ -d "$dir" ]] || continue
            name=$(basename "$dir")
            REPOS+=("$dir|packages/$cat_name/$name")
          done
        done
        ;;
      legacy | explicit)
        REPOS=("${PROJECT_INCLUDES[@]}")
        ;;
      *)
        echo "ERROR: unknown dense mode '$proj_mode' for project '$proj_name'" >&2
        exit 1
        ;;
    esac

    echo "Found ${#REPOS[@]} repos to index under $AOSP_ROOT"
    echo ""

    SUCCEEDED=0
    FAILED=0
    SKIPPED=0

    for entry in "${REPOS[@]}"; do
      source_dir="${entry%%|*}"
      repo_name="${entry##*|}"

      if [[ "${INDEXING_SKIP_SOURCE_SCAN:-0}" == "1" ]]; then
        file_count=1
      else
        file_count=$(find "$source_dir" -maxdepth 5 -type f \( -name "*.java" -o -name "*.kt" -o -name "*.cpp" -o -name "*.c" -o -name "*.h" -o -name "*.aidl" -o -name "*.go" -o -name "*.rs" -o -name "*.py" \) -print -quit 2> /dev/null | wc -l)
      fi
      if [[ "$file_count" -eq 0 ]]; then
        echo "SKIP  $repo_name (no source files)"
        SKIPPED=$((SKIPPED + 1))
        continue
      fi

      echo "===== INDEX  $repo_name ====="
      start_indexing_job "$repo_name" dense "$proj_name"
      job_exit=0

      build_cmd=(
        "$BUILD_SCRIPT"
        --source-dir "$source_dir"
        --repo-name "$repo_name"
        --project-name "$proj_name"
        --collection-name "$proj_collection"
      )

      if [[ "${INDEXING_DRY_RUN:-0}" == "1" ]]; then
        echo "DRY_RUN  $repo_name (skipping docker)"
        echo "DRY_RUN_CMD  ${build_cmd[*]}"
      elif "${build_cmd[@]}" 2>&1 | tee -a "${LOG_PATH:-/dev/stderr}"; then
        : # success — handled below
      else
        job_exit=$?
      fi

      if [[ $job_exit -eq 0 ]]; then
        finish_indexing_job success 0
        SUCCEEDED=$((SUCCEEDED + 1))
        echo "DONE  $repo_name"
      else
        finish_indexing_job fail $job_exit
        FAILED=$((FAILED + 1))
        echo "FAIL  $repo_name"
      fi
      echo ""
    done

    echo "--- PROJECT $proj_name: ${#REPOS[@]} repos  Succeeded: $SUCCEEDED  Failed: $FAILED  Skipped: $SKIPPED ---"
    echo ""
    TOTAL_SUCCEEDED=$((TOTAL_SUCCEEDED + SUCCEEDED))
    TOTAL_FAILED=$((TOTAL_FAILED + FAILED))
    TOTAL_SKIPPED=$((TOTAL_SKIPPED + SKIPPED))
  done

  echo "==============================="
  echo "ALL PROJECTS  Succeeded: $TOTAL_SUCCEEDED  Failed: $TOTAL_FAILED  Skipped: $TOTAL_SKIPPED"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
