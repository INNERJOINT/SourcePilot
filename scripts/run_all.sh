#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  AOSP Code Search all-in-one startup script
#
#  Startup order:
#    1. sparse-index-zoekt (index service)
#    2. Dense retrieval stack (when DENSE_ENABLED=true)
#    3. Neo4j structural index (when STRUCTURAL_ENABLED=true)
#    4. SourcePilot (search engine API, Docker)
#    5. MCP Server (protocol proxy, Docker)
#    6. sp-cockpit (audit dashboard, Docker)
#
#  Configuration:
#    Read config from .env file (see .env.example)
#    Can also override via CLI env vars
#
#  Usage:
#    ./run_all.sh                           # Use .env config
#    ZOEKT_INDEX_PATH=/path ./run_all.sh    # Override index path
#    DENSE_ENABLED=true ./run_all.sh        # Include dense retrieval stack
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)

# Load shared libraries
source "$DIR/share/_common.sh"
_common_parse_help "$@"
source "$DIR/share/_env.sh"
source "$DIR/share/_infra.sh"

# ── Configuration ────────────────────────────────────
ZOEKT_URL="${ZOEKT_URL:-http://localhost:6070}"
MCP_PORT="${MCP_PORT:-8888}"
SP_COCKPIT_PORT="${SP_COCKPIT_PORT:-9100}"
SP_COCKPIT_ENABLED="${SP_COCKPIT_ENABLED:-true}"

# ── Process management ───────────────────────────────
PIDS=()
SP_COCKPIT_RUNNING=false
ZOEKT_DOCKER=false

cleanup() {
  echo "" >&2
  info "Stopping all services..."
  docker compose -f "$COMPOSE_FILE" stop sourcepilot-gateway mcp-server sp-cockpit 2> /dev/null || true
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
  info "All services stopped."
}
trap cleanup EXIT INT TERM

# ── 1. Start sparse-index-zoekt ─────────────────────────
infra_start_zoekt

# ── 2. Start Dense retrieval stack ────────────────────
infra_start_dense

# ── 3. Start Neo4j ───────────────────────────────────
infra_start_structural

# ── 4. Start SourcePilot ─────────────────────────────
infra_start_sourcepilot

# ── 5. Start MCP Server ──────────────────────────────
export SOURCEPILOT_URL="http://localhost:9000"
infra_start_mcp

# ── 6. Start sp-cockpit ──────────────────────────────
infra_start_cockpit

# ── Startup complete ─────────────────────────────────
echo "" >&2
echo "════════════════════════════════════════════" >&2
echo "  All services started:" >&2
if [ "$ZOEKT_DOCKER" = true ]; then
  echo "    sparse-index-zoekt  (Docker)       ($ZOEKT_URL)" >&2
else
  echo "    sparse-index-zoekt  PID ${PIDS[0]:-?}  ($ZOEKT_URL)" >&2
fi
if [ "${DENSE_ENABLED:-false}" = "true" ]; then
  echo "    Dense stack      (Docker)       (Qdrant :6333)" >&2
fi
if [ "${STRUCTURAL_ENABLED:-false}" = "true" ]; then
  echo "    Neo4j            (Docker)       (bolt://localhost:7687)" >&2
fi
echo "    SourcePilot      (Docker)       (http://localhost:9000)" >&2
echo "    MCP Server       (Docker)       (http://0.0.0.0:${MCP_PORT}/mcp)" >&2
if [ "$SP_COCKPIT_ENABLED" = "true" ]; then
  if [ "$SP_COCKPIT_RUNNING" = true ]; then
    echo "    sp-cockpit       (Docker)       (http://localhost:${SP_COCKPIT_PORT})" >&2
  else
    echo "    sp-cockpit       (startup failed/timed out)" >&2
  fi
fi
echo "" >&2
echo "  Press Ctrl+C to stop all services" >&2
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
