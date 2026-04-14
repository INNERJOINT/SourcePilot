#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  SourcePilot HTTP API 启动脚本
#
#  用法：
#    ./run_sourcepilot.sh                          # 默认 0.0.0.0:9000
#    ./run_sourcepilot.sh --host 127.0.0.1         # 自定义监听地址
#    ./run_sourcepilot.sh --port 9001              # 自定义端口
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)

# 使用 pyenv 虚拟环境
VENV_PYTHON="/opt/pyenv/versions/dify_py3_env/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
    echo "Warning: $VENV_PYTHON not found, using system python3" >&2
    VENV_PYTHON="python3"
fi

export PYTHONPATH="$DIR/../src"

# 默认参数
HOST="0.0.0.0"
PORT="9000"

# 解析命令行参数
while [ $# -gt 0 ]; do
    case "$1" in
        --host)
            HOST="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

echo "SourcePilot HTTP API" >&2
echo "Listening: http://${HOST}:${PORT}" >&2

exec "$VENV_PYTHON" -m uvicorn app:app --host "$HOST" --port "$PORT"
