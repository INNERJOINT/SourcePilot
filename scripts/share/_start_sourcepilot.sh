#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  SourcePilot HTTP API startup script
#
#  Usage:
#    ./run_sourcepilot.sh                          # default 0.0.0.0:9000
#    ./run_sourcepilot.sh --host 127.0.0.1         # custom listen address
#    ./run_sourcepilot.sh --port 9001              # custom listen port
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)

# Load shared libraries
source "$DIR/_common.sh"

# Load .env config (if exists)
source "$DIR/_env.sh"

main() {
  # 3-tier interpreter fallback
  VENV_PYTHON="${VENV_PYTHON:-/opt/pyenv/versions/dify_py3_env/bin/python3}"
  if [ ! -x "$VENV_PYTHON" ]; then
    echo "Warning: $VENV_PYTHON not found, using system python3" >&2
    VENV_PYTHON="python3"
  fi

  export PYTHONPATH="$PROJ_ROOT/src"

  # Default audit log path: anchored to project root, aligned with sp-cockpit's default SP_COCKPIT_AUDIT_LOG_PATH
  export AUDIT_LOG_FILE="${AUDIT_LOG_FILE:-$PROJ_ROOT/audit.log}"

  # Default parameters
  HOST="0.0.0.0"
  PORT="9000"

  # Parse command-line arguments
  while [ $# -gt 0 ]; do
    case "$1" in
      -h | --help) _common_parse_help --help ;;
      --host)
        if [ $# -lt 2 ] || [ -z "$2" ]; then
          echo "Error: --host requires a non-empty value" >&2
          exit 2
        fi
        HOST="$2"
        shift 2
        ;;
      --port)
        if [ $# -lt 2 ] || [ -z "$2" ]; then
          echo "Error: --port requires a non-empty value" >&2
          exit 2
        fi
        if ! [[ "$2" =~ ^[0-9]+$ ]] || [ "$2" -lt 1 ] || [ "$2" -gt 65535 ]; then
          echo "Error: --port must be an integer between 1 and 65535, got '$2'" >&2
          exit 2
        fi
        PORT="$2"
        shift 2
        ;;
      *)
        echo "Unknown argument: $1" >&2
        exit 1
        ;;
    esac
  done

  echo "SourcePilot HTTP API" >&2
  echo "Listening: http://${HOST}:${PORT}" >&2

  exec "$VENV_PYTHON" -m uvicorn app:app --host "$HOST" --port "$PORT"
}

# Only run main when executed directly, not when sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
