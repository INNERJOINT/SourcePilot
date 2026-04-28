#!/usr/bin/env bash
# Run shell static checks for repository scripts.
#
# Usage:
#   bash tests/shell/static_check.sh
#
# Checks:
#   - shellcheck for lint issues
#   - shfmt -d for formatting drift
#   - bash -n for syntax errors

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

shopt -s globstar nullglob
shell_scripts=(scripts/**/*.sh)

if ((${#shell_scripts[@]} == 0)); then
  echo "No shell scripts found under scripts/" >&2
  exit 0
fi

missing_tools=()
for tool in shellcheck shfmt; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    missing_tools+=("$tool")
  fi
done

if ((${#missing_tools[@]} > 0)); then
  printf 'Missing required tool(s): %s\n' "${missing_tools[*]}" >&2
  exit 127
fi

shellcheck -x -S error "${shell_scripts[@]}"

set +e
shfmt_diff="$(shfmt -d -i 2 -ci -sr "${shell_scripts[@]}")"
shfmt_status=$?
set -e

if [[ -n "$shfmt_diff" ]]; then
  printf '%s\n' "$shfmt_diff"
  exit 1
fi

if ((shfmt_status != 0)); then
  exit "$shfmt_status"
fi

for f in "${shell_scripts[@]}"; do
  bash -n "$f"
done
