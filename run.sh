#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  Zoekt-Dify Query API 启动脚本
#
#  默认监听 445 端口。
#  由于 445 < 1024，需要 root 权限或对 python3 设置 cap_net_bind_service。
#
#  用法:
#    sudo ./run.sh                  # 直接用 root 启动
#    ./run.sh                       # 如已设置 capability
#
#  环境变量 (可选):
#    ZOEKT_URL              Zoekt webserver 地址 (默认 http://localhost:6070)
#    API_KEY                鉴权密钥 (默认 your-api-key)
#    PORT                   监听端口 (默认 445)
#    DEFAULT_CONTEXT_LINES  上下文窗口行数 (默认 20)
# ──────────────────────────────────────────────────────

set -euo pipefail
cd "$(dirname "$0")"

# 默认端口
PORT="${PORT:-445}"

echo "=========================================="
echo "  Zoekt-Dify Query API"
echo "  Listening on 0.0.0.0:${PORT}"
echo "  Zoekt URL: ${ZOEKT_URL:-http://localhost:6070}"
echo "=========================================="

# 直接使用 pyenv 虚拟环境中的 python（兼容 sudo）
VENV_PYTHON="/opt/pyenv/versions/dify_py3_env/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
    echo "Error: $VENV_PYTHON not found. Please check pyenv virtualenv name."
    exit 1
fi

exec "$VENV_PYTHON" -m uvicorn app:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --log-level info
