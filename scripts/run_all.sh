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
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)

# Load shared libraries
source "$DIR/share/_common.sh"
_common_parse_help "$@"
source "$DIR/share/_env.sh"
source "$DIR/share/_infra.sh"

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
	# 1) Stop bare processes (MCP / sp-cockpit when not in Docker mode)
	for pid in "${PIDS[@]}"; do
		if kill -0 "$pid" 2>/dev/null; then
			kill "$pid" 2>/dev/null || true
		fi
	done
	sleep 1
	for pid in "${PIDS[@]}"; do
		if kill -0 "$pid" 2>/dev/null; then
			kill -9 "$pid" 2>/dev/null || true
		fi
	done
	wait 2>/dev/null || true

	# 2) Stop Docker services started by this script
	if [ "${STOP_DOCKER_ON_EXIT:-true}" = "true" ]; then
		info "Stopping Docker containers..."
		local _svcs=()
		# zoekt: stop all sparse-index-zoekt* services
		# shellcheck disable=SC2207
		local _zoekt_svcs=($(docker compose -f "$COMPOSE_FILE" ps --services 2>/dev/null | grep '^sparse-index-zoekt' || true))
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
			docker compose -f "$COMPOSE_FILE" stop "${_svcs[@]}" >/dev/null 2>&1 || true
		fi
	fi
	info "All services stopped."
}
trap cleanup EXIT INT TERM

# ── 1a. Start sparse-index-zoekt (Docker, multi-project) ─
infra_start_zoekt

# ── 1b. Start Dense / Structural infrastructure (Docker) ─
infra_start_dense
infra_start_structural

# ── 2. Start SourcePilot (Docker) ─────────────────────
infra_start_sourcepilot

# ── 3. Start MCP Server ──────────────────────────────
export SOURCEPILOT_URL
MCP_PID=""
if [ "$MCP_DOCKER" = "true" ]; then
	infra_start_mcp
	MCP_RUNNING=true
else
	if curl -sf "http://localhost:${MCP_PORT}/health" >/dev/null 2>&1; then
		info "Detected MCP Server already running (port ${MCP_PORT}), skipping startup"
		MCP_RUNNING=true
	else
		info "Starting MCP Server (bare, streamable-http, port ${MCP_PORT})..."
		env PYTHONPATH="$PROJ_ROOT/mcp-server" \
			"$VENV_PYTHON" -m mcp_server --transport streamable-http \
			--host 0.0.0.0 --port "$MCP_PORT" &
		PIDS+=($!)
		MCP_PID=${PIDS[-1]}

		for i in $(seq 1 "$MAX_RETRIES"); do
			if curl -sf "http://localhost:${MCP_PORT}/health" >/dev/null 2>&1; then
				info "MCP Server ready (PID $MCP_PID)"
				MCP_RUNNING=true
				break
			fi
			[ "$i" -eq "$MAX_RETRIES" ] && die "MCP Server startup timed out (${MAX_RETRIES}s)"
			sleep 1
		done
	fi
fi

# ── 4. Start sp-cockpit ──────────────────────────────
SP_COCKPIT_PID=""
if [ "$SP_COCKPIT_ENABLED" = "true" ]; then
	if [ "$SP_COCKPIT_DOCKER" = "true" ]; then
		infra_start_cockpit
	else
		if curl -sf "http://localhost:${SP_COCKPIT_PORT}/api/health" >/dev/null 2>&1; then
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

			for i in $(seq 1 "$MAX_RETRIES"); do
				if curl -sf "http://localhost:${SP_COCKPIT_PORT}/api/health" >/dev/null 2>&1; then
					info "sp-cockpit ready (PID $SP_COCKPIT_PID)"
					SP_COCKPIT_RUNNING=true
					break
				fi
				[ "$i" -eq "$MAX_RETRIES" ] && warn "sp-cockpit startup timed out (${MAX_RETRIES}s), continuing with other services"
				sleep 1
			done
		fi
	fi
fi

# ── Startup summary ───────────────────────────────────
_mode_label() { if [ "$1" = "true" ]; then echo "Docker"; else echo "bare"; fi; }

echo "" >&2
echo "════════════════════════════════════════════" >&2
echo "  All services started:" >&2
if [ "$ZOEKT_DOCKER" = true ]; then
	echo "    sparse-index-zoekt  (Docker)          ($ZOEKT_URL ...)" >&2
else
	echo "    sparse-index-zoekt  (native)          ($ZOEKT_URL)" >&2
fi
if [ "${DENSE_ENABLED:-false}" = "true" ]; then
	echo "    Dense retrieval    (Docker)          (Qdrant :6333)" >&2
fi
if [ "${STRUCTURAL_ENABLED:-false}" = "true" ]; then
	echo "    Neo4j            (Docker)          (bolt://localhost:7687)" >&2
fi
echo "    SourcePilot      (Docker)                      ($SOURCEPILOT_URL)" >&2
if [ "$MCP_RUNNING" = true ]; then
	if [ -n "$MCP_PID" ]; then
		echo "    MCP Server       PID $MCP_PID (bare, streamable-http) (http://0.0.0.0:${MCP_PORT}/mcp)" >&2
	else
		echo "    MCP Server       ($(_mode_label "$MCP_DOCKER"))              (http://0.0.0.0:${MCP_PORT}/mcp)" >&2
	fi
else
	echo "    MCP Server       (startup failed/timed out)" >&2
fi
if [ "$SP_COCKPIT_ENABLED" = "true" ]; then
	if [ -n "$SP_COCKPIT_PID" ]; then
		echo "    sp-cockpit       PID $SP_COCKPIT_PID (bare)   (http://localhost:${SP_COCKPIT_PORT})" >&2
	elif [ "$SP_COCKPIT_RUNNING" = true ]; then
		echo "    sp-cockpit       ($(_mode_label "$SP_COCKPIT_DOCKER"))              (http://localhost:${SP_COCKPIT_PORT})" >&2
	else
		echo "    sp-cockpit       (startup failed/timed out)" >&2
	fi
fi
echo "" >&2
echo "  MCP_DOCKER=$MCP_DOCKER  SP_COCKPIT_DOCKER=$SP_COCKPIT_DOCKER" >&2
echo "  Press Ctrl+C to stop all services" >&2
echo "════════════════════════════════════════════" >&2

# Wait for a bare process to exit; if no bare processes were started,
# keep the script in the foreground until Ctrl+C.
if [ "${#PIDS[@]}" -eq 0 ]; then
	info "No bare processes started (all services running in Docker). Press Ctrl+C to exit."
	while true; do sleep 3600; done
else
	wait -n 2>/dev/null || true
	info "A bare process exited; shutting down all services..."
fi
