#!/usr/bin/env bash
# _infra.sh — reusable infrastructure startup functions for scripts/
#
# Source this file after _common.sh:
#   source "$DIR/_common.sh"
#   source "$DIR/_infra.sh"
#
# Functions:
#   infra_start_zoekt        — detect Docker/native zoekt, start + healthcheck
#   infra_start_dense        — docker compose up dense stack (etcd/minio/milvus/embedding-server)
#   infra_start_graph        — docker compose up neo4j
#   infra_start_cockpit      — start sp-cockpit + healthcheck
#
# Conventions:
#   - Each function appends background PIDs to the caller's PIDS array (if declared).
#   - Each function sets state variables (e.g. ZOEKT_DOCKER) in the caller's scope.
#   - COMPOSE_FILE is the canonical docker-compose path.
#   - MAX_RETRIES controls healthcheck timeout (default 30).

set -euo pipefail

# Guard against double-sourcing
if [[ -n "${_INFRA_LIB_LOADED:-}" ]]; then
    return 0
fi
_INFRA_LIB_LOADED=1

# Canonical paths
_INFRA_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
COMPOSE_FILE="${COMPOSE_FILE:-$_INFRA_DIR/../deploy/docker-compose.yml}"
MAX_RETRIES="${MAX_RETRIES:-30}"

# ── zoekt ─────────────────────────────────────────────────
infra_start_zoekt() {
    local zoekt_url="${ZOEKT_URL:-http://localhost:6070}"
    ZOEKT_DOCKER=false

    if curl -sf "$zoekt_url/" >/dev/null 2>&1; then
        if docker compose -f "$COMPOSE_FILE" ps --status running --services 2>/dev/null | grep -qx 'zoekt-webserver'; then
            info "检测到 zoekt-webserver 容器已在运行，重启容器..."
            docker compose -f "$COMPOSE_FILE" restart zoekt-webserver >/dev/null
            for i in $(seq 1 $MAX_RETRIES); do
                curl -sf "$zoekt_url/" >/dev/null 2>&1 && { info "zoekt-webserver 重启就绪"; break; }
                [ "$i" -eq "$MAX_RETRIES" ] && die "zoekt-webserver 重启后健康检查超时"
                sleep 1
            done
        else
            info "检测到 zoekt-webserver 已在运行 ($zoekt_url，非 compose)，跳过原生启动"
        fi
        ZOEKT_DOCKER=true
        return
    fi

    # 原生模式：需要 ZOEKT_INDEX_PATH
    local index_path="${ZOEKT_INDEX_PATH:-}"
    if [ -z "$index_path" ]; then
        die "ZOEKT_INDEX_PATH 未设置。请在 .env 中设置或通过环境变量传入。"
    fi
    if [ ! -d "$index_path" ]; then
        die "ZOEKT_INDEX_PATH 目录不存在: $index_path"
    fi

    info "启动 zoekt-webserver (index: $index_path)..."
    zoekt-webserver -index "$index_path" &
    PIDS+=($!)
    local pid=${PIDS[-1]}

    for i in $(seq 1 $MAX_RETRIES); do
        if curl -sf "$zoekt_url/" >/dev/null 2>&1; then
            info "zoekt-webserver 就绪 (PID $pid)"
            return
        fi
        [ "$i" -eq "$MAX_RETRIES" ] && die "zoekt-webserver 启动超时 (${MAX_RETRIES}s)"
        sleep 1
    done
}

# ── dense stack (etcd + minio + milvus + embedding-server) ──
infra_start_dense() {
    if [ "${DENSE_ENABLED:-false}" != "true" ]; then
        return
    fi

    info "启动 Dense 检索栈 (etcd + minio + milvus + embedding-server)..."
    docker compose -f "$COMPOSE_FILE" up -d etcd minio milvus embedding-server

    # 等待 Milvus 健康检查
    info "等待 Milvus 就绪..."
    for i in $(seq 1 $MAX_RETRIES); do
        if curl -sf "http://localhost:${MILVUS_HEALTH_PORT:-9091}/healthz" >/dev/null 2>&1; then
            info "Milvus 就绪"
            return
        fi
        [ "$i" -eq "$MAX_RETRIES" ] && warn "Milvus 健康检查超时 (${MAX_RETRIES}s)，Dense 检索可能不可用"
        sleep 1
    done
}

# ── graph (neo4j) ──────────────────────────────────────────
infra_start_graph() {
    if [ "${GRAPH_ENABLED:-false}" != "true" ]; then
        return
    fi

    local neo4j_host="${GRAPH_NEO4J_URI:-bolt://localhost:7687}"
    local neo4j_port
    neo4j_port=$(echo "$neo4j_host" | grep -oP ':\K[0-9]+$' || echo "7687")
    local neo4j_user="${GRAPH_NEO4J_USER:-neo4j}"
    local neo4j_pass="${GRAPH_NEO4J_PASSWORD:-sourcepilot}"

    if nc -z localhost "$neo4j_port" 2>/dev/null; then
        info "检测到 Neo4j 已在运行 (port $neo4j_port)，跳过启动"
        return
    fi

    info "启动 Neo4j (docker compose)..."
    docker compose -f "$COMPOSE_FILE" up -d neo4j

    for i in $(seq 1 $MAX_RETRIES); do
        if docker compose -f "$COMPOSE_FILE" exec -T neo4j \
            cypher-shell -u "$neo4j_user" -p "$neo4j_pass" 'RETURN 1' >/dev/null 2>&1; then
            info "Neo4j 就绪"
            return
        fi
        [ "$i" -eq "$MAX_RETRIES" ] && warn "Neo4j 启动超时 (${MAX_RETRIES}s)，图谱检索可能不可用"
        sleep 1
    done
}

# ── sp-cockpit ────────────────────────────────────────────
infra_start_cockpit() {
    local cockpit_port="${SP_COCKPIT_PORT:-9100}"
    local cockpit_enabled="${SP_COCKPIT_ENABLED:-true}"

    if [ "$cockpit_enabled" != "true" ]; then
        return
    fi

    if curl -sf "http://localhost:${cockpit_port}/api/health" >/dev/null 2>&1; then
        if docker compose -f "$COMPOSE_FILE" ps --status running --services 2>/dev/null | grep -qx 'sp-cockpit'; then
            info "检测到 sp-cockpit 容器已在运行，重启容器..."
            docker compose -f "$COMPOSE_FILE" restart sp-cockpit >/dev/null
            for i in $(seq 1 $MAX_RETRIES); do
                curl -sf "http://localhost:${cockpit_port}/api/health" >/dev/null 2>&1 && { info "sp-cockpit 重启就绪"; SP_COCKPIT_RUNNING=true; return; }
                [ "$i" -eq "$MAX_RETRIES" ] && { warn "sp-cockpit 重启后健康检查超时"; return; }
                sleep 1
            done
        else
            info "检测到 sp-cockpit 已在运行 (port ${cockpit_port}，非 compose)，跳过启动"
            SP_COCKPIT_RUNNING=true
            return
        fi
    fi

    info "启动 sp-cockpit (port ${cockpit_port})..."
    SP_COCKPIT_PORT="$cockpit_port" "$_INFRA_DIR/../sp-cockpit/scripts/run_sp_cockpit.sh" &
    PIDS+=($!)
    SP_COCKPIT_PID=${PIDS[-1]}

    for i in $(seq 1 $MAX_RETRIES); do
        if curl -sf "http://localhost:${cockpit_port}/api/health" >/dev/null 2>&1; then
            info "sp-cockpit 就绪 (PID $SP_COCKPIT_PID)"
            SP_COCKPIT_RUNNING=true
            return
        fi
        [ "$i" -eq "$MAX_RETRIES" ] && warn "sp-cockpit 启动超时 (${MAX_RETRIES}s)，继续运行其他服务"
        sleep 1
    done
}
