#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  Shared .env loader — sourced by all run_*.sh scripts
#
#  Loads .env file from the project root (if it exists).
#  Only sets variables not already defined in the environment,
#  so CLI environment variables always take precedence.
#
#  Supported .env syntax:
#    KEY=VALUE
#    export KEY=VALUE
#    # comment lines
#    KEY="quoted value"
#    KEY='quoted value'
#    KEY=value  # inline comments
#
#  Not supported:
#    multi-line values, variable interpolation ($VAR), escape sequences
#
#  Toggles:
#    SOURCEPILOT_ENV_NO_AUTOLOAD=1  — define load_env_file() only, skip auto-load
#    SOURCEPILOT_ENV_QUIET=1        — suppress "Loaded config from..." message
# ──────────────────────────────────────────────────────

set -euo pipefail

# Source guard — safe to source multiple times
if [ "${_ENV_LIB_LOADED:-}" = "1" ]; then
  return 0 2> /dev/null || true
fi
_ENV_LIB_LOADED=1

# Load a .env file. Only sets variables not already defined in the environment.
# Usage: load_env_file [path]   (defaults to $PROJ_ROOT/.env)
load_env_file() {
  local env_file="${1:-$PROJ_ROOT/.env}"

  if [ ! -f "$env_file" ]; then
    return 0
  fi

  while IFS= read -r line || [ -n "$line" ]; do
    # Skip blank lines and comments
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue

    # Strip export prefix
    line="${line#export }"
    line="${line#export	}"

    # Split key=value (split at first =)
    key="${line%%=*}"
    value="${line#*=}"

    # Trim whitespace from key
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"

    # Skip invalid keys
    [[ -z "$key" || "$key" =~ [^a-zA-Z0-9_] ]] && continue

    # Strip inline comments from value (only for unquoted values)
    case "$value" in
      \"*\" | \'*\')
        # Quoted value: strip surrounding quotes
        value="${value:1:${#value}-2}"
        ;;
      *)
        # Unquoted value: strip inline comments (after #)
        value="${value%%[[:space:]]#*}"
        # Trim trailing whitespace
        value="${value%"${value##*[![:space:]]}"}"
        ;;
    esac

    # Only set if not already defined
    if [ -z "${!key+x}" ]; then
      export "$key=$value"
    fi
  done < "$env_file"

  if [ "${SOURCEPILOT_ENV_QUIET:-}" != "1" ]; then
    echo "Loaded config from $env_file" >&2
  fi
}

# Auto-load unless suppressed
if [ "${SOURCEPILOT_ENV_NO_AUTOLOAD:-}" != "1" ]; then
  load_env_file
fi
