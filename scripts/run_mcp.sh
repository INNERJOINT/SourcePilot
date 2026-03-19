#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  AOSP Code Search MCP Server 启动脚本
#
#  支持两种传输模式：
#    ./run_mcp.sh                               # stdio 模式（默认，供 Claude Code / Cursor 等本地工具）
#    ./run_mcp.sh --transport streamable-http    # Streamable HTTP 模式（供远程客户端 HTTP 访问）
#
#  Streamable HTTP 模式额外参数：
#    --host 0.0.0.0     监听地址（默认 0.0.0.0）
#    --port 8888        监听端口（默认 8888）
#
#  环境变量：
#    ZOEKT_URL   Zoekt webserver 地址 (默认 http://localhost:6070)
#    MCP_PORT    Streamable HTTP 监听端口 (可选，等价于 --port)
# ──────────────────────────────────────────────────────

set -euo pipefail
cd "$(dirname "$0")"

# 使用 pyenv 虚拟环境
VENV_PYTHON="/opt/pyenv/versions/dify_py3_env/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
    echo "Warning: $VENV_PYTHON not found, using system python3" >&2
    VENV_PYTHON="python3"
fi

DIR=$(cd "$(dirname "$0")" && pwd)
export PYTHONPATH="$DIR/../src"

# 如果没传参数，默认 stdio 模式
if [ $# -eq 0 ]; then
    echo "AOSP Code Search MCP Server (stdio)" >&2
    echo "Zoekt URL: ${ZOEKT_URL:-http://localhost:6070}" >&2
    exec "$VENV_PYTHON" -m aosp_search.mcp_server
fi

# 检查是否是 streamable-http 模式，打印提示信息
for arg in "$@"; do
    if [ "$arg" = "streamable-http" ]; then
        MCP_PORT="${MCP_PORT:-8888}"
        echo "AOSP Code Search MCP Server (streamable-http)" >&2
        echo "Zoekt URL: ${ZOEKT_URL:-http://localhost:6070}" >&2
        echo "MCP Endpoint: http://0.0.0.0:${MCP_PORT}/mcp" >&2
        break
    fi
done

exec "$VENV_PYTHON" -m aosp_search.mcp_server "$@"
