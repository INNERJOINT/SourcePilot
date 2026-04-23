#!/usr/bin/env bash
# _common.sh — shared logging, error handling, and CLI helpers for scripts/
#
# Source this file at the top of any non-library script:
#   source "$(dirname "$0")/_common.sh"
#
# Interface contract (frozen — do not change signatures):
#   log LEVEL MSG              — timestamped [LEVEL] message to stderr (INFO/WARN/ERROR)
#   info MSG                   — shorthand for log INFO
#   warn MSG                   — shorthand for log WARN
#   die MSG [CODE]             — log ERROR then exit with CODE (default 1)
#   run CMD...                 — log the command, then exec it, preserving exit code
#   usage_die [MSG]            — print caller's header comment (optionally prefixed), exit 1
#   _common_parse_help "$@"    — if $1 is -h|--help, print caller's header comment and exit 0

set -euo pipefail

# Guard against double-sourcing
if [[ -n "${_COMMON_LIB_LOADED:-}" ]]; then
    return 0
fi
_COMMON_LIB_LOADED=1

# Colors (disabled when stderr is not a TTY or NO_COLOR is set)
if [[ -t 2 && -z "${NO_COLOR:-}" ]]; then
    _C_GREEN=$'\033[0;32m'
    _C_YELLOW=$'\033[1;33m'
    _C_RED=$'\033[0;31m'
    _C_RESET=$'\033[0m'
else
    _C_GREEN=''
    _C_YELLOW=''
    _C_RED=''
    _C_RESET=''
fi

log() {
    local level="${1:-INFO}"
    shift || true
    local msg="$*"
    local color=''
    case "$level" in
        INFO)  color="$_C_GREEN" ;;
        WARN)  color="$_C_YELLOW" ;;
        ERROR) color="$_C_RED" ;;
    esac
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    printf '[%s] %s[%s]%s %s\n' "$ts" "$color" "$level" "$_C_RESET" "$msg" >&2
}

info() { log INFO "$*"; }
warn() { log WARN "$*"; }

die() {
    local msg="${1:-unspecified error}"
    local code="${2:-1}"
    log ERROR "$msg"
    exit "$code"
}

run() {
    log INFO "+ $*"
    "$@"
}

# Print the leading comment block of the caller script (the file that sourced _common.sh
# or the file that invoked usage_die). Strips the shebang and comment markers.
_print_caller_header() {
    local caller="${BASH_SOURCE[2]:-${BASH_SOURCE[1]}}"
    [[ -r "$caller" ]] || return 0
    awk '
        NR == 1 && /^#!/ { next }
        /^#/ { sub(/^#[[:space:]]?/, "", $0); print; next }
        { exit }
    ' "$caller"
}

usage_die() {
    local prefix="${1:-}"
    if [[ -n "$prefix" ]]; then
        printf '%s\n\n' "$prefix" >&2
    fi
    _print_caller_header >&2
    exit 1
}

_common_parse_help() {
    case "${1:-}" in
        -h|--help)
            _print_caller_header
            exit 0
            ;;
    esac
}
