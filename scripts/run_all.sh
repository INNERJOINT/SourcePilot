#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  AOSP Code Search full-stack startup script
#
#  Infrastructure (zoekt/qdrant/neo4j) and SourcePilot always run in Docker.
#  MCP and SP Cockpit default to bare processes but can be switched to Docker
#  via .env variables MCP_DOCKER and SP_COCKPIT_DOCKER.
#
#  Usage:
#    ./run_all.sh                               # Default: MCP+cockpit bare, rest Docker
#    MCP_DOCKER=true ./run_all.sh               # MCP in Docker
#    SP_COCKPIT_DOCKER=true ./run_all.sh        # sp-cockpit in Docker
#    DENSE_ENABLED=true ./run_all.sh            # Include dense retrieval stack
#    STRUCTURAL_ENABLED=true ./run_all.sh       # Include Neo4j structural retrieval
#    RESTART_CONTAINERS=false ./run_all.sh      # Keep already-running containers as-is
#                                               # (default: stop existing containers first
#                                               #  for a clean restart)
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# Load shared libraries
source "$DIR/share/_common.sh"
_common_parse_help "$@"
source "$DIR/share/_env.sh"
source "$DIR/share/_infra.sh"

# ── Helpers (pure, sourceable) ────────────────────────
_mode_label() { if [ "$1" = "true" ]; then echo "Docker"; else echo "bare"; fi; }

# _print_startup_summary
#   Renders the post-startup banner. Reads (must be set in caller scope):
#     ZOEKT_URL ZOEKT_DOCKER DENSE_ENABLED STRUCTURAL_ENABLED
#     SOURCEPILOT_URL MCP_RUNNING MCP_PID MCP_DOCKER MCP_PORT
#     SP_COCKPIT_ENABLED SP_COCKPIT_PID SP_COCKPIT_RUNNING SP_COCKPIT_DOCKER SP_COCKPIT_PORT
#   Pure: only writes to stderr. No side effects on services. Exposed for tests.
_print_startup_summary() {
  echo "" >&2
  echo "════════════════════════════════════════════" >&2
  echo "  SourcePilot — All services started:" >&2
  if [ "${ZOEKT_DOCKER:-false}" = true ] || [ "${ZOEKT_DOCKER:-false}" = "true" ]; then
    echo "    sparse-index-zoekt  (Docker)          (${ZOEKT_URL} ...)" >&2
  else
    echo "    sparse-index-zoekt  (native)          (${ZOEKT_URL})" >&2
  fi
  if [ "${DENSE_ENABLED:-false}" = "true" ]; then
    echo "    Dense retrieval    (Docker)          (Qdrant :6333)" >&2
  fi
  if [ "${STRUCTURAL_ENABLED:-false}" = "true" ]; then
    echo "    Neo4j            (Docker)          (bolt://localhost:7687)" >&2
  fi
  echo "    SourcePilot      (Docker)                      (${SOURCEPILOT_URL})" >&2
  if [ "${MCP_RUNNING:-false}" = true ] || [ "${MCP_RUNNING:-false}" = "true" ]; then
    if [ -n "${MCP_PID:-}" ]; then
      echo "    MCP Server       PID ${MCP_PID} (bare, streamable-http) (http://0.0.0.0:${MCP_PORT}/mcp)" >&2
    else
      echo "    MCP Server       ($(_mode_label "${MCP_DOCKER:-false}"))              (http://0.0.0.0:${MCP_PORT}/mcp)" >&2
    fi
  else
    echo "    MCP Server       (startup failed/timed out)" >&2
  fi
  if [ "${SP_COCKPIT_ENABLED:-true}" = "true" ]; then
    if [ -n "${SP_COCKPIT_PID:-}" ]; then
      echo "    sp-cockpit       PID ${SP_COCKPIT_PID} (bare)   (http://localhost:${SP_COCKPIT_PORT})" >&2
    elif [ "${SP_COCKPIT_RUNNING:-false}" = true ] || [ "${SP_COCKPIT_RUNNING:-false}" = "true" ]; then
      echo "    sp-cockpit       ($(_mode_label "${SP_COCKPIT_DOCKER:-false}"))              (http://localhost:${SP_COCKPIT_PORT})" >&2
    else
      echo "    sp-cockpit       (startup failed/timed out)" >&2
    fi
  fi
  echo "" >&2
  echo "  MCP_DOCKER=${MCP_DOCKER:-false}  SP_COCKPIT_DOCKER=${SP_COCKPIT_DOCKER:-false}" >&2
  echo "  Press Ctrl+C to stop all services" >&2
  echo "════════════════════════════════════════════" >&2
}

main() {
  # ── Configuration ─────────────────────────────────────
  ZOEKT_URL="${ZOEKT_URL:-http://localhost:6070}"
  SOURCEPILOT_PORT="${SOURCEPILOT_PORT:-9000}"
  SOURCEPILOT_URL="${SOURCEPILOT_URL:-http://localhost:${SOURCEPILOT_PORT}}"
  MCP_PORT="${MCP_PORT:-8888}"
  SP_COCKPIT_PORT="${SP_COCKPIT_PORT:-9100}"
  SP_COCKPIT_ENABLED="${SP_COCKPIT_ENABLED:-true}"

  # Docker toggle for MCP and SP Cockpit (default: bare process)
  MCP_DOCKER="${MCP_DOCKER:-false}"
  SP_COCKPIT_DOCKER="${SP_COCKPIT_DOCKER:-false}"

  # Whether to stop already-running compose containers before starting them
  # (default: true => clean restart; set false to reuse running containers as-is).
  RESTART_CONTAINERS="${RESTART_CONTAINERS:-true}"

  # Whether the cleanup trap stops Docker containers on exit. Defaults to
  # RESTART_CONTAINERS so opting out of restarts also keeps the containers
  # alive between runs (e.g. for slow-loading zoekt indexes).
  STOP_DOCKER_ON_EXIT="${STOP_DOCKER_ON_EXIT:-$RESTART_CONTAINERS}"

  # ── pyenv virtualenv (only needed when running bare processes) ─
  VENV_PYTHON="${VENV_PYTHON:-/opt/pyenv/versions/dify_py3_env/bin/python3}"
  if [ "$MCP_DOCKER" != "true" ] || [ "$SP_COCKPIT_DOCKER" != "true" ]; then
    if [ ! -x "$VENV_PYTHON" ]; then
      die "Python runtime not found or not executable: $VENV_PYTHON. Set VENV_PYTHON to the project Python interpreter."
    fi
  fi

  # ── Process management ────────────────────────────────
  PIDS=()
  ZOEKT_DOCKER=false
  SP_COCKPIT_RUNNING=false
  MCP_RUNNING=false

  cleanup() {
    echo "" >&2
    info "Stopping all services..."
    for pid in "${PIDS[@]}"; do
      if kill -0 "$pid" 2> /dev/null; then
        kill "$pid" 2> /dev/null || true
      fi
    done
    sleep 1
    for pid in "${PIDS[@]}"; do
      if kill -0 "$pid" 2> /dev/null; then
        kill -9 "$pid" 2> /dev/null || true
      fi
    done
    wait 2> /dev/null || true

    if [ "${STOP_DOCKER_ON_EXIT:-true}" = "true" ]; then
      info "Stopping Docker containers..."
      local _svcs=()
      # shellcheck disable=SC2207
      local _zoekt_svcs=($("$DOCKER_BIN" compose -f "$COMPOSE_FILE" ps --services 2> /dev/null | grep '^sparse-index-zoekt' || true))
      _svcs+=("${_zoekt_svcs[@]}")
      _svcs+=(sourcepilot-gateway)
      if [ "$MCP_DOCKER" = "true" ]; then
        _svcs+=(mcp-server)
      fi
      if [ "$SP_COCKPIT_DOCKER" = "true" ]; then
        _svcs+=(sp-cockpit)
      fi
      if [ "${DENSE_ENABLED:-false}" = "true" ]; then
        _svcs+=(qdrant dense-index-coderankembed)
      fi
      if [ "${STRUCTURAL_ENABLED:-false}" = "true" ]; then
        _svcs+=(neo4j)
      fi
      if [ "${#_svcs[@]}" -gt 0 ]; then
        "$DOCKER_BIN" compose -f "$COMPOSE_FILE" stop "${_svcs[@]}" > /dev/null 2>&1 || true
      fi
    fi
    info "All services stopped."
  }
  trap cleanup EXIT INT TERM

  # ── Pre-start: stop existing compose containers for a clean restart ──
  # Skip when RESTART_CONTAINERS=false so users can keep slow-loading
  # services (e.g. zoekt with thousands of shards) running across runs.
  if [ "$RESTART_CONTAINERS" = "true" ]; then
    info "RESTART_CONTAINERS=true: stopping existing compose containers before startup..."
    local _pre_svcs=()
    # shellcheck disable=SC2207
    local _pre_zoekt=($("$DOCKER_BIN" compose -f "$COMPOSE_FILE" ps --services 2> /dev/null | grep '^sparse-index-zoekt' || true))
    _pre_svcs+=("${_pre_zoekt[@]}")
    _pre_svcs+=(sourcepilot-gateway)
    if [ "$MCP_DOCKER" = "true" ]; then
      _pre_svcs+=(mcp-server)
    fi
    if [ "$SP_COCKPIT_DOCKER" = "true" ]; then
      _pre_svcs+=(sp-cockpit)
    fi
    if [ "${DENSE_ENABLED:-false}" = "true" ]; then
      _pre_svcs+=(qdrant dense-index-coderankembed)
    fi
    if [ "${STRUCTURAL_ENABLED:-false}" = "true" ]; then
      _pre_svcs+=(neo4j)
    fi
    if [ "${#_pre_svcs[@]}" -gt 0 ]; then
      "$DOCKER_BIN" compose -f "$COMPOSE_FILE" stop "${_pre_svcs[@]}" > /dev/null 2>&1 || true
    fi
  else
    info "RESTART_CONTAINERS=false: reusing already-running containers if present"
  fi

  infra_start_zoekt
  infra_start_dense
  infra_start_structural
  infra_start_sourcepilot

  export SOURCEPILOT_URL
  MCP_PID=""
  if [ "$MCP_DOCKER" = "true" ]; then
    infra_start_mcp
    MCP_RUNNING=true
  else
    if "$CURL_BIN" -sf "http://localhost:${MCP_PORT}/health" > /dev/null 2>&1; then
      info "Detected MCP Server already running (port ${MCP_PORT}), skipping startup"
      MCP_RUNNING=true
    else
      info "Starting MCP Server (bare, streamable-http, port ${MCP_PORT})..."
      env PYTHONPATH="$PROJ_ROOT/mcp-server" \
        "$VENV_PYTHON" -m mcp_server --transport streamable-http \
        --host 0.0.0.0 --port "$MCP_PORT" &
      PIDS+=($!)
      MCP_PID=${PIDS[-1]}

      if _infra_wait_http "http://localhost:${MCP_PORT}/health" "MCP Server ready (PID $MCP_PID)" "$MAX_RETRIES" die; then
        MCP_RUNNING=true
      fi
    fi
  fi

  SP_COCKPIT_PID=""
  if [ "$SP_COCKPIT_ENABLED" = "true" ]; then
    if [ "$SP_COCKPIT_DOCKER" = "true" ]; then
      infra_start_cockpit
    else
      if "$CURL_BIN" -sf "http://localhost:${SP_COCKPIT_PORT}/api/health" > /dev/null 2>&1; then
        info "Detected sp-cockpit already running (port ${SP_COCKPIT_PORT}), skipping startup"
        SP_COCKPIT_RUNNING=true
      else
        export SP_COCKPIT_AUDIT_LOG_PATH="${SP_COCKPIT_AUDIT_LOG_PATH:-$PROJ_ROOT/audit.log}"
        export SP_COCKPIT_AUDIT_DB_PATH="${SP_COCKPIT_AUDIT_DB_PATH:-$PROJ_ROOT/sp-cockpit/data/audit.db}"
        export SP_COCKPIT_HOST="${SP_COCKPIT_HOST:-0.0.0.0}"
        export SP_COCKPIT_PORT="$SP_COCKPIT_PORT"
        export SP_COCKPIT_FRONTEND_DIST="${SP_COCKPIT_FRONTEND_DIST:-$PROJ_ROOT/sp-cockpit/frontend/dist}"

        [ -f "$SP_COCKPIT_AUDIT_LOG_PATH" ] || touch "$SP_COCKPIT_AUDIT_LOG_PATH"
        mkdir -p "$(dirname "$SP_COCKPIT_AUDIT_DB_PATH")"

        info "Starting sp-cockpit (bare, port ${SP_COCKPIT_PORT})..."
        (cd "$PROJ_ROOT/sp-cockpit" && env PYTHONPATH="$PROJ_ROOT/sp-cockpit" \
          "$VENV_PYTHON" -m sp_cockpit.main) &
        PIDS+=($!)
        SP_COCKPIT_PID=${PIDS[-1]}

        if _infra_wait_http "http://localhost:${SP_COCKPIT_PORT}/api/health" "sp-cockpit ready (PID $SP_COCKPIT_PID)" "$MAX_RETRIES" warn; then
          SP_COCKPIT_RUNNING=true
        fi
      fi
    fi
  fi

  _print_startup_summary

  if [ "${#PIDS[@]}" -eq 0 ]; then
    info "No bare processes started (all services running in Docker). Press Ctrl+C to exit."
    while true; do sleep 3600; done
  else
    wait -n 2> /dev/null || true
    info "A bare process exited; shutting down all services..."
  fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
