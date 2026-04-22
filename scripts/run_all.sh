#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  AOSP Code Search 一键启动脚本
#
#  启动顺序：
#    1. zoekt-webserver（索引服务）
#    2. SourcePilot（搜索引擎 API）
#    3. MCP Server（协议代理）
#
#  配置：
#    从 .env 文件读取配置（参见 .env.example）
#    也可通过命令行环境变量覆盖
#
#  用法：
#    ./run_all.sh                           # 使用 .env 配置
#    ZOEKT_INDEX_PATH=/path ./run_all.sh    # 覆盖索引路径
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)

# 加载 .env 配置（如果存在）
source "$DIR/_env.sh"

# ── 配置 ──────────────────────────────────────────────
ZOEKT_URL="${ZOEKT_URL:-http://localhost:6070}"
MCP_TRANSPORT="${MCP_TRANSPORT:-streamable-http}"
MCP_PORT="${MCP_PORT:-8888}"
AUDIT_VIEWER_PORT="${AUDIT_VIEWER_PORT:-9100}"
AUDIT_VIEWER_ENABLED="${AUDIT_VIEWER_ENABLED:-true}"

# ── 进程管理 ──────────────────────────────────────────
PIDS=()

cleanup() {
    echo "" >&2
    echo "正在停止所有服务..." >&2
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
    echo "所有服务已停止。" >&2
}
trap cleanup EXIT INT TERM

MAX_RETRIES=30

# ── 1. 启动 zoekt-webserver ──────────────────────────
# 检测 Docker 模式下的 zoekt 是否已在运行；若是，重启容器以保证使用最新配置
ZOEKT_DOCKER=false
if curl -sf "$ZOEKT_URL/" >/dev/null 2>&1; then
    if docker compose -f "$DIR/../docker-compose.yml" ps --status running --services 2>/dev/null | grep -qx 'zoekt-webserver'; then
        echo "检测到 zoekt-webserver 容器已在运行，重启容器..." >&2
        docker compose -f "$DIR/../docker-compose.yml" restart zoekt-webserver >/dev/null
        for i in $(seq 1 $MAX_RETRIES); do
            curl -sf "$ZOEKT_URL/" >/dev/null 2>&1 && { echo "zoekt-webserver 重启就绪" >&2; break; }
            [ "$i" -eq "$MAX_RETRIES" ] && { echo "Error: zoekt-webserver 重启后健康检查超时" >&2; exit 1; }
            sleep 1
        done
    else
        echo "检测到 zoekt-webserver 已在运行 ($ZOEKT_URL，非 compose)，跳过原生启动" >&2
    fi
    ZOEKT_DOCKER=true
fi

if [ "$ZOEKT_DOCKER" = false ]; then
    # 原生模式：需要 ZOEKT_INDEX_PATH
    ZOEKT_INDEX_PATH="${ZOEKT_INDEX_PATH:-}"
    if [ -z "$ZOEKT_INDEX_PATH" ]; then
        echo "Error: ZOEKT_INDEX_PATH 未设置" >&2
        echo "请在 .env 中设置或通过环境变量传入，例如：" >&2
        echo "  ZOEKT_INDEX_PATH=/mnt/code/ACE/.repo/.zoekt/ $0" >&2
        exit 1
    fi
    if [ ! -d "$ZOEKT_INDEX_PATH" ]; then
        echo "Error: ZOEKT_INDEX_PATH 目录不存在: $ZOEKT_INDEX_PATH" >&2
        exit 1
    fi

    echo "启动 zoekt-webserver (index: $ZOEKT_INDEX_PATH)..." >&2
    zoekt-webserver -index "$ZOEKT_INDEX_PATH" &
    PIDS+=($!)
    ZOEKT_PID=${PIDS[-1]}

    # 等待 zoekt 就绪
    for i in $(seq 1 $MAX_RETRIES); do
        if curl -sf "$ZOEKT_URL/" >/dev/null 2>&1; then
            echo "zoekt-webserver 就绪 (PID $ZOEKT_PID)" >&2
            break
        fi
        if [ "$i" -eq "$MAX_RETRIES" ]; then
            echo "Error: zoekt-webserver 启动超时 (${MAX_RETRIES}s)" >&2
            exit 1
        fi
        sleep 1
    done
fi

# ── 1b. 启动 Neo4j（可选，GRAPH_ENABLED=true 时生效）─────
GRAPH_ENABLED="${GRAPH_ENABLED:-false}"
NEO4J_BOLT_HOST="${GRAPH_NEO4J_URI:-bolt://localhost:7687}"
# 从 URI 中提取端口（默认 7687）
NEO4J_PORT=$(echo "$NEO4J_BOLT_HOST" | grep -oP ':\K[0-9]+$' || echo "7687")
NEO4J_USER="${GRAPH_NEO4J_USER:-neo4j}"
NEO4J_PASS="${GRAPH_NEO4J_PASSWORD:-sourcepilot}"

if [ "$GRAPH_ENABLED" = "true" ]; then
    # 检查 Neo4j Bolt 端口是否已就绪
    if nc -z localhost "$NEO4J_PORT" 2>/dev/null; then
        echo "检测到 Neo4j 已在运行 (port $NEO4J_PORT)，跳过启动" >&2
    else
        echo "启动 Neo4j (docker compose)..." >&2
        docker compose -f "$DIR/../graph-deploy/docker-compose.yml" up -d
        # 等待 Neo4j 就绪
        for i in $(seq 1 $MAX_RETRIES); do
            if docker compose -f "$DIR/../graph-deploy/docker-compose.yml" exec -T neo4j \
                cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASS" 'RETURN 1' >/dev/null 2>&1; then
                echo "Neo4j 就绪" >&2
                break
            fi
            if [ "$i" -eq "$MAX_RETRIES" ]; then
                echo "Warning: Neo4j 启动超时 (${MAX_RETRIES}s)，图谱检索可能不可用" >&2
                break
            fi
            sleep 1
        done
    fi
fi

# ── 2. 启动 SourcePilot ──────────────────────────────
echo "启动 SourcePilot (port 9000)..." >&2
"$DIR/run_sourcepilot.sh" &
PIDS+=($!)
SP_PID=${PIDS[-1]}

# 等待 SourcePilot 就绪
for i in $(seq 1 $MAX_RETRIES); do
    if curl -sf http://localhost:9000/api/health >/dev/null 2>&1; then
        echo "SourcePilot 就绪 (PID $SP_PID)" >&2
        break
    fi
    if [ "$i" -eq "$MAX_RETRIES" ]; then
        echo "Error: SourcePilot 启动超时 (${MAX_RETRIES}s)" >&2
        exit 1
    fi
    sleep 1
done

# ── 3. 启动 MCP Server ───────────────────────────────
# 设置 SOURCEPILOT_URL 使 run_mcp.sh 跳过自动启动 SourcePilot
# 注意：必须在调用 run_mcp.sh 之前 export，
# 这样子进程的 _env.sh 不会用 .env 中的值覆盖它
export SOURCEPILOT_URL="http://localhost:9000"

echo "启动 MCP Server (${MCP_TRANSPORT}, port ${MCP_PORT})..." >&2

MCP_ARGS=()
if [ "$MCP_TRANSPORT" != "stdio" ]; then
    MCP_ARGS+=(--transport "$MCP_TRANSPORT" --port "$MCP_PORT")
fi

"$DIR/run_mcp.sh" "${MCP_ARGS[@]}" &
PIDS+=($!)
MCP_PID=${PIDS[-1]}

# ── 4. 启动 audit-viewer ─────────────────────────────
AV_PID=""
AV_RUNNING=false
if [ "$AUDIT_VIEWER_ENABLED" = "true" ]; then
    if curl -sf "http://localhost:${AUDIT_VIEWER_PORT}/api/health" >/dev/null 2>&1; then
        if docker compose -f "$DIR/../docker-compose.yml" ps --status running --services 2>/dev/null | grep -qx 'audit-viewer'; then
            echo "检测到 audit-viewer 容器已在运行，重启容器..." >&2
            docker compose -f "$DIR/../docker-compose.yml" restart audit-viewer >/dev/null
            for i in $(seq 1 $MAX_RETRIES); do
                curl -sf "http://localhost:${AUDIT_VIEWER_PORT}/api/health" >/dev/null 2>&1 && { echo "audit-viewer 重启就绪" >&2; AV_RUNNING=true; break; }
                [ "$i" -eq "$MAX_RETRIES" ] && { echo "Warning: audit-viewer 重启后健康检查超时" >&2; break; }
                sleep 1
            done
        else
            echo "检测到 audit-viewer 已在运行 (port ${AUDIT_VIEWER_PORT}，非 compose)，跳过启动" >&2
            AV_RUNNING=true
        fi
    else
        echo "启动 audit-viewer (port ${AUDIT_VIEWER_PORT})..." >&2
        AUDIT_VIEWER_PORT="$AUDIT_VIEWER_PORT" "$DIR/../audit-viewer/scripts/run_audit_viewer.sh" &
        PIDS+=($!)
        AV_PID=${PIDS[-1]}

        for i in $(seq 1 $MAX_RETRIES); do
            if curl -sf "http://localhost:${AUDIT_VIEWER_PORT}/api/health" >/dev/null 2>&1; then
                echo "audit-viewer 就绪 (PID $AV_PID)" >&2
                AV_RUNNING=true
                break
            fi
            if [ "$i" -eq "$MAX_RETRIES" ]; then
                echo "Warning: audit-viewer 启动超时 (${MAX_RETRIES}s)，继续运行其他服务" >&2
                break
            fi
            sleep 1
        done
    fi
fi

# ── 启动完成 ──────────────────────────────────────────
echo "" >&2
echo "════════════════════════════════════════════" >&2
echo "  所有服务已启动：" >&2
if [ "$ZOEKT_DOCKER" = true ]; then
echo "    zoekt-webserver  (Docker, already running)  ($ZOEKT_URL)" >&2
else
echo "    zoekt-webserver  PID $ZOEKT_PID  ($ZOEKT_URL)" >&2
fi
echo "    SourcePilot      PID $SP_PID   (http://localhost:9000)" >&2
if [ "$MCP_TRANSPORT" != "stdio" ]; then
echo "    MCP Server       PID $MCP_PID   (http://0.0.0.0:${MCP_PORT}/mcp)" >&2
else
echo "    MCP Server       PID $MCP_PID   (stdio)" >&2
fi
if [ "$AUDIT_VIEWER_ENABLED" = "true" ]; then
    if [ -n "$AV_PID" ]; then
        echo "    audit-viewer     PID $AV_PID   (http://localhost:${AUDIT_VIEWER_PORT})" >&2
    elif [ "$AV_RUNNING" = true ]; then
        echo "    audit-viewer     (already running)  (http://localhost:${AUDIT_VIEWER_PORT})" >&2
    else
        echo "    audit-viewer     (启动失败/超时)" >&2
    fi
fi
if [ "$GRAPH_ENABLED" = "true" ]; then
    echo "    Neo4j            (bolt://localhost:${NEO4J_PORT})" >&2
fi
echo "" >&2
echo "  按 Ctrl+C 停止所有服务" >&2
echo "════════════════════════════════════════════" >&2

# 等待任意子进程退出
wait -n 2>/dev/null || true
echo "某个服务异常退出，正在关闭所有服务..." >&2
