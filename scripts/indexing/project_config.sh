#!/usr/bin/env bash
# project_config.sh — Shell helper for multi-AOSP project configuration.
# Source this file; do not execute directly.
#
# Exports:
#   load_projects()           — emits "name|source_root|collection_name" lines to stdout
#   fallback_single_project() — emits single line from AOSP_SOURCE_ROOT env var

set -euo pipefail

# Resolve project root (two dirs up from this script's directory)
_PC_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_PC_PROJ_ROOT="$(cd "${_PC_SCRIPT_DIR}/../.." && pwd)"
_PC_CONFIG="${_PC_PROJ_ROOT}/config/projects.yaml"

fallback_single_project() {
    local source_root="${AOSP_SOURCE_ROOT:-/mnt/code/ACE}"
    local name
    name="$(basename "${source_root}" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '_' | sed 's/_*$//')"
    local collection_name="aosp_code_${name}"
    echo "${name}|${source_root}|${collection_name}"
}

load_projects() {
    if [[ ! -f "${_PC_CONFIG}" ]]; then
        fallback_single_project
        return
    fi

    python3 - "${_PC_CONFIG}" <<'PYEOF'
import sys, yaml, re, os
from pathlib import Path

config_path = sys.argv[1]
name_re = re.compile(r'^[a-z0-9_]+$')

with open(config_path) as fh:
    data = yaml.safe_load(fh)

for raw in data.get('projects', []):
    name = raw['name']
    source_root = raw['source_root']
    collection_name = raw.get('collection_name', f'aosp_code_{name}')
    if not name_re.match(name):
        print(f"ERROR: invalid project name: {name}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isabs(source_root):
        print(f"ERROR: source_root must be absolute: {source_root}", file=sys.stderr)
        sys.exit(1)
    print(f"{name}|{source_root}|{collection_name}")
PYEOF
}
