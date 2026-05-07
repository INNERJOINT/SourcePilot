#!/usr/bin/env bash
# _infra.sh — reusable infrastructure startup functions for scripts/
#
# Source this file after _common.sh:
#   source "$DIR/_common.sh"
#   source "$DIR/_infra.sh"
#
# Helpers (internal):
#   _infra_require_cmd       — die if a command is missing (with install hint)
#   _infra_wait_http         — poll a URL until healthy or retries exhausted
#   _infra_wait_tcp          — poll a host:port until open or retries exhausted
#
# Functions (public):
#   infra_start_zoekt        — detect Docker/native zoekt, start + healthcheck
#   infra_start_dense        — docker compose up dense stack (qdrant + dense-index-coderankembed)
#   infra_start_structural  — docker compose up neo4j
#   infra_start_sourcepilot  — docker compose up sourcepilot-gateway + healthcheck
#   infra_start_mcp          — docker compose up mcp-server + healthcheck
#   infra_start_cockpit      — docker compose up sp-cockpit + healthcheck
#
# Conventions:
#   - Each function sets state variables (e.g. ZOEKT_DOCKER) in the caller's scope.
#   - COMPOSE_FILE is the canonical docker-compose path.
#   - MAX_RETRIES controls healthcheck timeout (default 30).
#   - INFRA_SLEEP_SECONDS controls sleep between retries (default 1; set 0 in tests).

set -euo pipefail

# Guard against double-sourcing
if [[ -n "${_INFRA_LIB_LOADED:-}" ]]; then
  return 0
fi
_INFRA_LIB_LOADED=1

# Injectable command paths (override for testing)
CURL_BIN="${CURL_BIN:-curl}"
NC_BIN="${NC_BIN:-nc}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Canonical paths
_INFRA_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
COMPOSE_FILE="${COMPOSE_FILE:-$_INFRA_DIR/../../deploy/docker-compose.yml}"
MAX_RETRIES="${MAX_RETRIES:-30}"
ZOEKT_MAX_RETRIES="${ZOEKT_MAX_RETRIES:-120}"
INFRA_SLEEP_SECONDS="${INFRA_SLEEP_SECONDS:-1}"

# ── shared helpers ───────────────────────────────────────────

# _infra_require_cmd <cmd> [install_hint]
# Backward-compat wrapper around _common_require_cmd (now exits EXIT_DEPS=3).
_infra_require_cmd() {
  _common_require_cmd "$@"
}

# _infra_wait_http <url> <label> [max_retries] [die_on_fail]
# Poll <url> with curl until success or retries exhausted.
# die_on_fail: "die" (default) or "warn".
_infra_wait_http() {
  local url="$1" label="$2"
  local retries="${3:-$MAX_RETRIES}"
  local on_fail="${4:-die}"
  local i
  for i in $(seq 1 "$retries"); do
    if "$CURL_BIN" -sf "$url" > /dev/null 2>&1; then
      info "$label ready"
      return 0
    fi
    if [ "$i" -eq "$retries" ]; then
      if [ "$on_fail" = "die" ]; then
        die "$label startup timed out (${retries}s)"
      else
        warn "$label startup timed out (${retries}s)"
        return 1
      fi
    fi
    sleep "$INFRA_SLEEP_SECONDS"
  done
}

# _infra_wait_tcp <host> <port> <label> [max_retries]
# Poll <host>:<port> with nc until open or retries exhausted.
_infra_wait_tcp() {
  local host="$1" port="$2" label="$3"
  local retries="${4:-$MAX_RETRIES}"
  _infra_require_cmd nc
  local i
  for i in $(seq 1 "$retries"); do
    if "$NC_BIN" -z "$host" "$port" 2> /dev/null; then
      return 0
    fi
    [ "$i" -eq "$retries" ] && return 1
    sleep "$INFRA_SLEEP_SECONDS"
  done
}

# _infra_ensure_network_access <network_name>
# In Docker-in-Docker setups, the host cannot reach containers via published
# ports.  If we detect we are running inside a container, connect it to the
# given Compose network so Docker DNS names resolve and we can probe services.
_infra_ensure_network_access() {
  local net="$1"
  [ -f /.dockerenv ] || return 0
  # Find our own container name by matching hostname
  local self
  self=$("$DOCKER_BIN" ps --filter "name=$(hostname)" --format '{{.Names}}' 2>/dev/null | head -1)
  # Fallback: try lowercase hostname
  [ -z "$self" ] && self=$("$DOCKER_BIN" ps --filter "name=$(hostname | tr '[:upper:]' '[:lower:]')" --format '{{.Names}}' 2>/dev/null | head -1)
  [ -z "$self" ] && return 0
  if ! "$DOCKER_BIN" network inspect "$net" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null | grep -qw "$self"; then
    "$DOCKER_BIN" network connect "$net" "$self" 2>/dev/null || true
  fi
}

# ── zoekt ─────────────────────────────────────────────────
# Multi-project Docker mode (run_all.sh): for each project in
# config/projects.yaml, ensure the corresponding compose service is
# running and healthy. The first project uses service "sparse-index-zoekt"
# (back-compat); subsequent projects use "sparse-index-zoekt-<name>".
#
# Native mode (single project, no projects.yaml) is preserved as a fallback:
# it spawns one zoekt-webserver bound to ZOEKT_INDEX_PATH on ZOEKT_URL.
infra_start_zoekt() {
  local projects_cfg="${PROJECTS_CONFIG_PATH:-${PROJ_ROOT:-$(pwd)}/config/projects.yaml}"

  if [ -f "$projects_cfg" ]; then
    # Parse (name, zoekt_url) pairs from YAML.
    _infra_require_cmd python3 "install python3 or set PROJECTS_CONFIG_PATH to skip YAML parsing"
    local entries
    entries=$(
      python3 - "$projects_cfg" << 'EOF'
import re, sys
text = open(sys.argv[1]).read()
projects = []
cur = {}
for line in text.splitlines():
    s = line.strip()
    if s.startswith('- name:'):
        if cur:
            projects.append(cur)
        cur = {'name': s.split(':', 1)[1].strip()}
        continue
    for key in ('zoekt_url',):
        m = re.match(rf'\s*{key}:\s*(.+)', line)
        if m and key not in cur:
            cur[key] = m.group(1).strip()
if cur:
    projects.append(cur)
for p in projects:
    name = p.get('name', '')
    url = p.get('zoekt_url', '')
    if name and url:
        port = re.search(r':(\d+)(?:/|$)', url)
        port = port.group(1) if port else '6070'
        print(f"{name}|{url}|{port}")
EOF
    )

    if [ -n "$entries" ]; then
      _infra_require_cmd curl
      _infra_require_cmd docker "install Docker or use native zoekt mode"
      local idx=0
      while IFS='|' read -r _name _url _port; do
        [ -z "$_name" ] && continue
        local svc="sparse-index-zoekt-${_name}"
        idx=$((idx + 1))

        # Resolve probe URL: prefer Docker DNS (works in DinD), fall back
        # to localhost with published port (works on bare host).
        local _probe_url="$_url"
        local _host_only="${_url#http://}"
        _host_only="${_host_only%%:*}"

        # Try to detect if already running before starting
        _infra_ensure_network_access sourcepilot-net
        if ! getent hosts "$_host_only" > /dev/null 2>&1; then
          local _published=""
          _published=$("$DOCKER_BIN" compose -f "$COMPOSE_FILE" port "$svc" 6070 2> /dev/null | awk -F: 'NR==1{print $NF}') || _published=""
          if [ -z "$_published" ]; then
            _published="$_port"
          fi
          _probe_url="http://localhost:${_published}"
        fi

        if curl -sf "$_probe_url/" > /dev/null 2>&1; then
          info "Detected ${svc} already running (${_probe_url}), skipping startup"
          ZOEKT_DOCKER=true
          continue
        fi

        info "Starting ${svc} (project=${_name}, probe=${_probe_url})..."
        "$DOCKER_BIN" compose -f "$COMPOSE_FILE" up -d "$svc"
        ZOEKT_DOCKER=true

        # After compose up, the network exists; re-join and re-resolve
        _infra_ensure_network_access sourcepilot-net
        if getent hosts "$_host_only" > /dev/null 2>&1; then
          _probe_url="$_url"
        elif [ "$_probe_url" != "$_url" ]; then
          local _published2=""
          _published2=$("$DOCKER_BIN" compose -f "$COMPOSE_FILE" port "$svc" 6070 2> /dev/null | awk -F: 'NR==1{print $NF}') || _published2=""
          if [ -n "$_published2" ]; then
            _probe_url="http://localhost:${_published2}"
          fi
        fi

        _infra_wait_http "$_probe_url/" "  ${svc}" "$ZOEKT_MAX_RETRIES" warn || true
      done <<< "$entries"
      return
    fi
  fi

  # ── Native fallback (no projects.yaml) ─────────────────
  _infra_require_cmd curl
  local zoekt_url="${ZOEKT_URL:-http://localhost:6070}"
  ZOEKT_DOCKER=false

  if curl -sf "$zoekt_url/" > /dev/null 2>&1; then
    info "Detected sparse-index-zoekt already running ($zoekt_url), skipping startup"
    ZOEKT_DOCKER=true
    return
  fi

  local index_path="${ZOEKT_INDEX_PATH:-}"
  if [ -z "$index_path" ]; then
    die "ZOEKT_INDEX_PATH not set. Set it in .env or pass via environment variable."
  fi
  if [ ! -d "$index_path" ]; then
    die "ZOEKT_INDEX_PATH directory does not exist: $index_path"
  fi

  _infra_require_cmd zoekt-webserver "install zoekt or use Docker mode"
  info "Starting sparse-index-zoekt (index: $index_path)..."
  zoekt-webserver -index "$index_path" &
  PIDS+=($!)
  local pid=${PIDS[-1]}

  _infra_wait_http "$zoekt_url/" "sparse-index-zoekt ready (PID $pid)" "$MAX_RETRIES" die
}

# ── dense stack (qdrant + dense-index-coderankembed) ──
infra_start_dense() {
  if [ "${DENSE_ENABLED:-false}" != "true" ]; then
    return
  fi

  _infra_require_cmd docker "install Docker to run the dense stack"
  _infra_require_cmd curl
  info "Starting dense retrieval stack (qdrant + dense-index-coderankembed)..."
  docker compose -f "$COMPOSE_FILE" up -d qdrant dense-index-coderankembed
  _infra_ensure_network_access sourcepilot-net

  local _qdrant_url="http://localhost:${QDRANT_PORT:-6333}"
  if getent hosts qdrant > /dev/null 2>&1; then
    _qdrant_url="http://qdrant:${QDRANT_PORT:-6333}"
  fi
  info "Waiting for Qdrant to be ready..."
  _infra_wait_http "${_qdrant_url}/healthz" "Qdrant" "$MAX_RETRIES" warn ||
    warn "dense retrieval may be unavailable"
}

# ── structural (neo4j) ──────────────────────────────────────────
infra_start_structural() {
  if [ "${STRUCTURAL_ENABLED:-false}" != "true" ]; then
    return
  fi

  local neo4j_host="${STRUCTURAL_NEO4J_URI:-bolt://localhost:7687}"
  local neo4j_port
  neo4j_port=$(echo "$neo4j_host" | grep -oP ':\K[0-9]+$' || echo "7687")
  local neo4j_user="${STRUCTURAL_NEO4J_USER:-neo4j}"
  local neo4j_pass="${STRUCTURAL_NEO4J_PASSWORD:-sourcepilot}"

  if _infra_wait_tcp localhost "$neo4j_port" "Neo4j" 1 2> /dev/null; then
    info "Detected Neo4j already running (port $neo4j_port), skipping startup"
    return
  fi

  _infra_require_cmd docker "install Docker to run Neo4j"
  info "Starting Neo4j (docker compose)..."
  docker compose -f "$COMPOSE_FILE" up -d neo4j

  for i in $(seq 1 "$MAX_RETRIES"); do
    if docker compose -f "$COMPOSE_FILE" exec -T neo4j \
      cypher-shell -u "$neo4j_user" -p "$neo4j_pass" 'RETURN 1' > /dev/null 2>&1; then
      info "Neo4j ready"
      return
    fi
    [ "$i" -eq "$MAX_RETRIES" ] && warn "Neo4j startup timed out (${MAX_RETRIES}s), structural retrieval may be unavailable"
    sleep "$INFRA_SLEEP_SECONDS"
  done
}

# ── sourcepilot-gateway ───────────────────────────────────
infra_start_sourcepilot() {
  _infra_require_cmd curl
  _infra_ensure_network_access sourcepilot-net
  local _gw_url="http://localhost:9000"
  if getent hosts sourcepilot-gateway > /dev/null 2>&1; then
    _gw_url="http://sourcepilot-gateway:9000"
  fi
  if curl -sf "${_gw_url}/api/health" > /dev/null 2>&1; then
    info "Detected SourcePilot already running (${_gw_url}), skipping startup"
    return
  fi
  _infra_require_cmd docker "install Docker to run sourcepilot-gateway"
  info "Starting sourcepilot-gateway (Docker)..."
  docker compose -f "$COMPOSE_FILE" up -d --build sourcepilot-gateway
  _infra_ensure_network_access sourcepilot-net
  if getent hosts sourcepilot-gateway > /dev/null 2>&1; then
    _gw_url="http://sourcepilot-gateway:9000"
  fi
  _infra_wait_http "${_gw_url}/api/health" "sourcepilot-gateway ready (Docker)" "$MAX_RETRIES" die
}

# ── mcp-server ────────────────────────────────────────────
infra_start_mcp() {
  _infra_require_cmd curl
  local mcp_port="${MCP_PORT:-8888}"
  _infra_ensure_network_access sourcepilot-net
  local _mcp_url="http://localhost:${mcp_port}"
  if getent hosts mcp-server > /dev/null 2>&1; then
    _mcp_url="http://mcp-server:${mcp_port}"
  fi
  if curl -sf "${_mcp_url}/health" > /dev/null 2>&1; then
    info "Detected MCP Server already running (${_mcp_url}), skipping startup"
    return
  fi
  _infra_require_cmd docker "install Docker to run mcp-server"
  info "Starting mcp-server (Docker)..."
  docker compose -f "$COMPOSE_FILE" up -d mcp-server
  _infra_ensure_network_access sourcepilot-net
  if getent hosts mcp-server > /dev/null 2>&1; then
    _mcp_url="http://mcp-server:${mcp_port}"
  fi
  _infra_wait_http "${_mcp_url}/health" "mcp-server ready (Docker)" "$MAX_RETRIES" die
}

# ── sp-cockpit ────────────────────────────────────────────
infra_start_cockpit() {
  local cockpit_port="${SP_COCKPIT_PORT:-9100}"
  local cockpit_enabled="${SP_COCKPIT_ENABLED:-true}"
  if [ "$cockpit_enabled" != "true" ]; then return; fi
  _infra_require_cmd curl
  _infra_ensure_network_access sourcepilot-net
  local _cockpit_url="http://localhost:${cockpit_port}"
  if getent hosts sp-cockpit > /dev/null 2>&1; then
    _cockpit_url="http://sp-cockpit:${cockpit_port}"
  fi
  if curl -sf "${_cockpit_url}/api/health" > /dev/null 2>&1; then
    info "Detected sp-cockpit already running (${_cockpit_url}), skipping startup"
    SP_COCKPIT_RUNNING=true
    return
  fi
  _infra_require_cmd docker "install Docker to run sp-cockpit"
  info "Starting sp-cockpit (Docker, port ${cockpit_port})..."
  docker compose -f "$COMPOSE_FILE" up -d sp-cockpit
  _infra_ensure_network_access sourcepilot-net
  if getent hosts sp-cockpit > /dev/null 2>&1; then
    _cockpit_url="http://sp-cockpit:${cockpit_port}"
  fi
  if _infra_wait_http "${_cockpit_url}/api/health" "sp-cockpit ready (Docker)" "$MAX_RETRIES" warn; then
    SP_COCKPIT_RUNNING=true
  else
    warn "continuing with other services"
  fi
}
