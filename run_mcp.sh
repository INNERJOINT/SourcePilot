#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  AOSP Code Search MCP Server 启动脚本
#
#  通过 stdio 模式启动（供 Claude Code / Cursor 等工具调用）
#
#  环境变量:
#    ZOEKT_URL   Zoekt webserver 地址 (默认 http://localhost:6070)
# ──────────────────────────────────────────────────────

set -euo pipefail
cd "$(dirname "$0")"

echo "AOSP Code Search MCP Server" >&2
echo "Zoekt URL: ${ZOEKT_URL:-http://localhost:6070}" >&2

# 使用 pyenv 虚拟环境
VENV_PYTHON="/opt/pyenv/versions/dify_py3_env/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
    echo "Warning: $VENV_PYTHON not found, using system python3" >&2
    VENV_PYTHON="python3"
fi

exec "$VENV_PYTHON" mcp_server.py "$@"
