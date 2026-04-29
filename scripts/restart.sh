#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  restart script
#
#  Stop target containers then restart.
#  Apply config changes after editing .env.
#
#  Usage:
#    ./restart.sh                      # Restart full stack (run_all.sh)
#    ./restart.sh --with-zoekt         # Also restart sparse-index-zoekt
#    ./restart.sh --only sp            # Restart only SourcePilot container
#    ./restart.sh --only mcp           # Restart only MCP
#    ./restart.sh --only av            # Restart only sp-cockpit
#    ./restart.sh --only sourcepilot   # Restart SourcePilot full stack (excluding MCP)
#    ./restart.sh --only dense         # Restart dense retrieval stack (docker compose)
#    ./restart.sh --only structural    # Restart Neo4j (docker compose)
#    ./restart.sh --stop               # Stop only, no restart
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)
source "$DIR/share/_common.sh"
source "$DIR/share/_env.sh"
source "$DIR/share/_infra.sh"

MCP_PORT="${MCP_PORT:-8888}"
SP_COCKPIT_PORT="${SP_COCKPIT_PORT:-9100}"
SP_PORT=9000
ZOEKT_PORT_DEFAULT=6070

WITH_ZOEKT=false
STOP_ONLY=false
ONLY=""

while [ $# -gt 0 ]; do
  case "$1" in
    --with-zoekt) WITH_ZOEKT=true ;;
    --stop) STOP_ONLY=true ;;
    --only)
      ONLY="${2:-}"
      shift
      ;;
    -h | --help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *) die "Unknown argument: $1" ;;
  esac
  shift
done

kill_port() {
  local port="$1"
  local name="$2"
  local pids
  pids=$(lsof -ti ":$port" 2> /dev/null || true)
  if [ -z "$pids" ]; then
    info "[$name] port $port is free, skipping"
    return
  fi
  info "[$name] Stopping processes on port $port: $pids"
  # shellcheck disable=SC2086
  kill $pids 2> /dev/null || true
  sleep 1
  pids=$(lsof -ti ":$port" 2> /dev/null || true)
  if [ -n "$pids" ]; then
    warn "[$name] Processes not responding, sending SIGKILL: $pids"
    # shellcheck disable=SC2086
    kill -9 $pids 2> /dev/null || true
  fi
}

# ── Stop phase ───────────────────────────────────────────
info "Stopping services..."

case "$ONLY" in
  dense)
    info "Restart dense retrieval stack (qdrant + dense-index-coderankembed)..."
    docker compose -f "$COMPOSE_FILE" restart qdrant dense-index-coderankembed
    info "Dense retrieval stack restarted"
    exit 0
    ;;
  structural)
    info "Restart Neo4j..."
    docker compose -f "$COMPOSE_FILE" restart neo4j
    info "Neo4j restarted"
    exit 0
    ;;
  sourcepilot)
    # Stop SourcePilot full stack containers (excluding MCP)
    info "[SourcePilot] Stopping container..."
    docker compose -f "$COMPOSE_FILE" stop sourcepilot-gateway 2> /dev/null || true
    info "[sp-cockpit] Stopping container..."
    docker compose -f "$COMPOSE_FILE" stop sp-cockpit 2> /dev/null || true
    if [ "$WITH_ZOEKT" = true ]; then
      kill_port "$ZOEKT_PORT_DEFAULT" "sparse-index-zoekt"
    fi
    if [ "$STOP_ONLY" = true ]; then
      info "stopped."
      exit 0
    fi
    info ""
    info "Starting services..."
    exec "$DIR/run_sourcepilot.sh"
    ;;
  mcp)
    info "[MCP] Stopping container..."
    docker compose -f "$COMPOSE_FILE" stop mcp-server 2> /dev/null || true
    ;;
  sp)
    info "[SourcePilot] Stopping container..."
    docker compose -f "$COMPOSE_FILE" stop sourcepilot-gateway 2> /dev/null || true
    ;;
  av)
    info "[sp-cockpit] Stopping container..."
    docker compose -f "$COMPOSE_FILE" stop sp-cockpit 2> /dev/null || true
    ;;
  "")
    info "[MCP] Stopping container..."
    docker compose -f "$COMPOSE_FILE" stop mcp-server 2> /dev/null || true
    info "[SourcePilot] Stopping container..."
    docker compose -f "$COMPOSE_FILE" stop sourcepilot-gateway 2> /dev/null || true
    info "[sp-cockpit] Stopping container..."
    docker compose -f "$COMPOSE_FILE" stop sp-cockpit 2> /dev/null || true
    if [ "$WITH_ZOEKT" = true ]; then
      kill_port "$ZOEKT_PORT_DEFAULT" "sparse-index-zoekt"
    fi
    ;;
  *)
    die "--only supports: sp | mcp | av | sourcepilot | dense | structural"
    ;;
esac

if [ "$STOP_ONLY" = true ]; then
  info "stopped."
  exit 0
fi

# ── Start phase ───────────────────────────────────────────
echo "" >&2
info "Starting services..."

case "$ONLY" in
  sp)
    docker compose -f "$COMPOSE_FILE" up -d sourcepilot-gateway
    ;;
  mcp)
    exec "$DIR/run_mcp.sh" --transport streamable-http
    ;;
  av)
    exec "$DIR/run_sp_cockpit.sh"
    ;;
  "")
    exec "$DIR/run_all.sh"
    ;;
esac
