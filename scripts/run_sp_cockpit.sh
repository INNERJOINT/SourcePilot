#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  SourcePilot Cockpit 启动脚本（FastAPI + React SPA）
#
#  用法：
#    ./run_sp_cockpit.sh                       # 默认 127.0.0.1:9100
#    ./run_sp_cockpit.sh --host 0.0.0.0        # 监听所有网卡
#    ./run_sp_cockpit.sh --port 9200           # 自定义端口
#    ./run_sp_cockpit.sh --build               # 启动前先构建前端
#    ./run_sp_cockpit.sh --no-frontend         # 仅启动后端 API
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)
PROJ_ROOT=$(cd "$DIR/.." && pwd)
APP_DIR="$PROJ_ROOT/sp-cockpit"

source "$DIR/_env.sh"

VENV_PYTHON="/opt/pyenv/versions/dify_py3_env/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
    echo "Warning: $VENV_PYTHON not found, using system python3" >&2
    VENV_PYTHON="python3"
fi

# 默认配置
HOST="${SP_COCKPIT_HOST:-127.0.0.1}"
PORT="${SP_COCKPIT_PORT:-9100}"
BUILD_FRONTEND=0
SERVE_FRONTEND=1

while [ $# -gt 0 ]; do
    case "$1" in
        --host)        HOST="$2"; shift 2 ;;
        --port)        PORT="$2"; shift 2 ;;
        --build)       BUILD_FRONTEND=1; shift ;;
        --no-frontend) SERVE_FRONTEND=0; shift ;;
        -h|--help)
            sed -n '2,12p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

# 默认日志路径与数据库路径
export SP_COCKPIT_AUDIT_LOG_PATH="${SP_COCKPIT_AUDIT_LOG_PATH:-$PROJ_ROOT/audit.log}"
export SP_COCKPIT_AUDIT_DB_PATH="${SP_COCKPIT_AUDIT_DB_PATH:-$APP_DIR/data/audit.db}"
export SP_COCKPIT_HOST="$HOST"
export SP_COCKPIT_PORT="$PORT"

if [ "$SERVE_FRONTEND" -eq 1 ]; then
    export SP_COCKPIT_FRONTEND_DIST="${SP_COCKPIT_FRONTEND_DIST:-$APP_DIR/frontend/dist}"
else
    export SP_COCKPIT_FRONTEND_DIST="/nonexistent"
fi

# 触发文件存在性
[ -f "$SP_COCKPIT_AUDIT_LOG_PATH" ] || touch "$SP_COCKPIT_AUDIT_LOG_PATH"
mkdir -p "$(dirname "$SP_COCKPIT_AUDIT_DB_PATH")"

# 可选：构建前端
if [ "$BUILD_FRONTEND" -eq 1 ]; then
    echo "Building frontend..." >&2
    (cd "$APP_DIR/frontend" && npm install --no-audit --no-fund && npm run build)
fi

if [ "$SERVE_FRONTEND" -eq 1 ] && [ ! -d "$SP_COCKPIT_FRONTEND_DIST" ]; then
    echo "Warning: frontend dist not found at $SP_COCKPIT_FRONTEND_DIST" >&2
    echo "         Run with --build, or use --no-frontend for API-only." >&2
fi

cd "$APP_DIR"
export PYTHONPATH="$APP_DIR"

echo "SourcePilot Cockpit" >&2
echo "  Log:      $SP_COCKPIT_AUDIT_LOG_PATH" >&2
echo "  DB:       $SP_COCKPIT_AUDIT_DB_PATH" >&2
echo "  Frontend: $SP_COCKPIT_FRONTEND_DIST" >&2
echo "  URL:      http://${HOST}:${PORT}" >&2

exec "$VENV_PYTHON" -m sp_cockpit.main
