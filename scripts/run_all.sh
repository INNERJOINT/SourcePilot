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
ZOEKT_INDEX_PATH="${ZOEKT_INDEX_PATH:-}"
ZOEKT_URL="${ZOEKT_URL:-http://localhost:6070}"
MCP_TRANSPORT="${MCP_TRANSPORT:-streamable-http}"
MCP_PORT="${MCP_PORT:-8888}"

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
    # 等待优雅退出，然后强制终止
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

# ── 启动完成 ──────────────────────────────────────────
echo "" >&2
echo "════════════════════════════════════════════" >&2
echo "  所有服务已启动：" >&2
echo "    zoekt-webserver  PID $ZOEKT_PID  ($ZOEKT_URL)" >&2
echo "    SourcePilot      PID $SP_PID   (http://localhost:9000)" >&2
if [ "$MCP_TRANSPORT" != "stdio" ]; then
echo "    MCP Server       PID $MCP_PID   (http://0.0.0.0:${MCP_PORT}/mcp)" >&2
else
echo "    MCP Server       PID $MCP_PID   (stdio)" >&2
fi
echo "" >&2
echo "  按 Ctrl+C 停止所有服务" >&2
echo "════════════════════════════════════════════" >&2

# 等待任意子进程退出
wait -n 2>/dev/null || true
echo "某个服务异常退出，正在关闭所有服务..." >&2
