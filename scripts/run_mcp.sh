#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  AOSP Code Search MCP Server startup script
#
#  Supports two transport modes:
#    ./run_mcp.sh                               # stdio mode (default, for local tools like Claude Code / Cursor)
#    ./run_mcp.sh --transport streamable-http    # Streamable HTTP mode (Docker, for remote HTTP clients)
#
#  Additional parameters for Streamable HTTP mode:
#    --host 0.0.0.0     listen address (default 0.0.0.0)
#    --port 8888        listen port (default 8888)
#
#  SourcePilot dependency:
#    stdio mode: If SOURCEPILOT_URL is not set, the script auto-starts SourcePilot in background
#    streamable-http mode: Started via Docker compose (SourcePilot + MCP Server)
#
#  Environment variables:
#    ZOEKT_URL        Zoekt webserver URL (default http://localhost:6070)
#    SOURCEPILOT_URL  SourcePilot API URL (stdio mode: auto-starts if not set)
#    MCP_PORT         Streamable HTTP listen port (optional, equivalent to --port)
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)

# Load shared libraries
source "$DIR/share/_common.sh"
_common_parse_help "$@"

# Load .env config (if present)
source "$DIR/share/_env.sh"

# ── streamable-http mode detection ────────────────────
IS_HTTP_MODE=false
for arg in "$@"; do
  if [ "$arg" = "streamable-http" ]; then
    IS_HTTP_MODE=true
    break
  fi
done

# ── streamable-http mode: using Docker ────────────────
if [ "$IS_HTTP_MODE" = true ]; then
  source "$DIR/share/_infra.sh"

  MCP_PORT="${MCP_PORT:-8888}"
  SP_COCKPIT_RUNNING=false

  cleanup() {
    echo "" >&2
    info "Stopping services..."
    docker compose -f "$COMPOSE_FILE" stop sourcepilot-gateway mcp-server 2> /dev/null || true
    info "Services stopped."
  }
  trap cleanup EXIT INT TERM

  export SOURCEPILOT_URL="http://localhost:9000"
  infra_start_sourcepilot
  infra_start_mcp

  echo "" >&2
  echo "════════════════════════════════════════════" >&2
  echo "  MCP Server (streamable-http) started:" >&2
  echo "    SourcePilot  (Docker)  (http://localhost:9000)" >&2
  echo "    MCP Server   (Docker)  (http://0.0.0.0:${MCP_PORT}/mcp)" >&2
  echo "" >&2
  echo "  Press Ctrl+C to stop services" >&2
  echo "════════════════════════════════════════════" >&2

  # Monitor Docker service health
  while true; do
    unhealthy=$(docker compose -f "$COMPOSE_FILE" ps --format json |
      jq -r 'select(.Health == "unhealthy" or .State == "exited") | .Service' 2> /dev/null || true)
    if [ -n "$unhealthy" ]; then
      warn "Unhealthy service: $unhealthy"
      break
    fi
    sleep 5
  done
  info "A service exited unexpectedly; shutting down all services..."
  exit 0
fi

# ── stdio mode: bare process startup ─────────────────
VENV_PYTHON="${VENV_PYTHON:-/opt/pyenv/versions/dify_py3_env/bin/python3}"
if [ ! -x "$VENV_PYTHON" ]; then
  echo "Warning: $VENV_PYTHON not found, using system python3" >&2
  VENV_PYTHON="python3"
fi

export PYTHONPATH="$DIR/../mcp-server"

SOURCEPILOT_PID=""

cleanup_stdio() {
  if [ -n "$SOURCEPILOT_PID" ]; then
    echo "Stopping SourcePilot (PID $SOURCEPILOT_PID)..." >&2
    kill "$SOURCEPILOT_PID" 2> /dev/null || true
    wait "$SOURCEPILOT_PID" 2> /dev/null || true
  fi
}
trap cleanup_stdio EXIT

if [ -z "${SOURCEPILOT_URL:-}" ]; then
  echo "SOURCEPILOT_URL not set, starting SourcePilot in background..." >&2
  "$DIR/share/_start_sourcepilot.sh" &
  SOURCEPILOT_PID=$!

  MAX_RETRIES=30
  RETRY_INTERVAL=1
  for i in $(seq 1 $MAX_RETRIES); do
    if curl -sf http://localhost:9000/api/health > /dev/null 2>&1; then
      echo "SourcePilot is ready (PID $SOURCEPILOT_PID)" >&2
      break
    fi
    if [ "$i" -eq "$MAX_RETRIES" ]; then
      echo "Error: SourcePilot failed to start after ${MAX_RETRIES}s" >&2
      exit 1
    fi
    sleep "$RETRY_INTERVAL"
  done

  export SOURCEPILOT_URL="http://localhost:9000"
else
  echo "Using existing SourcePilot: $SOURCEPILOT_URL" >&2
fi

echo "AOSP Code Search MCP Server (stdio)" >&2
echo "Zoekt URL: ${ZOEKT_URL:-http://localhost:6070}" >&2
echo "SourcePilot URL: $SOURCEPILOT_URL" >&2
exec "$VENV_PYTHON" -m mcp_server
