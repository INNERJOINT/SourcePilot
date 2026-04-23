#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  SourcePilot Cockpit 启动脚本（FastAPI + React SPA）
#
#  用法：
#    ./run_sp_cockpit.sh                       # Docker 模式（默认）
#    ./run_sp_cockpit.sh --bare                # 裸进程模式（pyenv，旧行为）
#    ./run_sp_cockpit.sh --bare --host 0.0.0.0 # 裸进程模式 + 自定义参数
#    ./run_sp_cockpit.sh --bare --port 9200    # 裸进程模式 + 自定义端口
#    ./run_sp_cockpit.sh --bare --build        # 裸进程模式 + 构建前端
#    ./run_sp_cockpit.sh --bare --no-frontend  # 裸进程模式 + 仅后端 API
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)

source "$DIR/share/_common.sh"

APP_DIR="$PROJ_ROOT/sp-cockpit"
source "$DIR/share/_env.sh"

# ── --bare 模式：裸进程（旧行为） ─────────────────────
for arg in "$@"; do
    if [ "$arg" = "--bare" ]; then
        # 移除 --bare 参数，转发其余参数
        BARE_ARGS=()
        for a in "$@"; do
            [ "$a" = "--bare" ] || BARE_ARGS+=("$a")
        done

        VENV_PYTHON="/opt/pyenv/versions/dify_py3_env/bin/python3"
        if [ ! -x "$VENV_PYTHON" ]; then
            echo "Warning: $VENV_PYTHON not found, using system python3" >&2
            VENV_PYTHON="python3"
        fi

        HOST="${SP_COCKPIT_HOST:-0.0.0.0}"
        PORT="${SP_COCKPIT_PORT:-9100}"
        BUILD_FRONTEND=0
        SERVE_FRONTEND=1

        set -- "${BARE_ARGS[@]+"${BARE_ARGS[@]}"}"
        while [ $# -gt 0 ]; do
            case "$1" in
                --host)        HOST="$2"; shift 2 ;;
                --port)        PORT="$2"; shift 2 ;;
                --build)       BUILD_FRONTEND=1; shift ;;
                --no-frontend) SERVE_FRONTEND=0; shift ;;
                -h|--help)
                    sed -n '2,10p' "$0"
                    exit 0
                    ;;
                *)
                    echo "Unknown argument: $1" >&2
                    exit 1
                    ;;
            esac
        done

        export SP_COCKPIT_AUDIT_LOG_PATH="${SP_COCKPIT_AUDIT_LOG_PATH:-$PROJ_ROOT/audit.log}"
        export SP_COCKPIT_AUDIT_DB_PATH="${SP_COCKPIT_AUDIT_DB_PATH:-$APP_DIR/data/audit.db}"
        export SP_COCKPIT_HOST="$HOST"
        export SP_COCKPIT_PORT="$PORT"

        if [ "$SERVE_FRONTEND" -eq 1 ]; then
            export SP_COCKPIT_FRONTEND_DIST="${SP_COCKPIT_FRONTEND_DIST:-$APP_DIR/frontend/dist}"
        else
            export SP_COCKPIT_FRONTEND_DIST="/nonexistent"
        fi

        [ -f "$SP_COCKPIT_AUDIT_LOG_PATH" ] || touch "$SP_COCKPIT_AUDIT_LOG_PATH"
        mkdir -p "$(dirname "$SP_COCKPIT_AUDIT_DB_PATH")"

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

        echo "SourcePilot Cockpit (bare)" >&2
        echo "  Log:      $SP_COCKPIT_AUDIT_LOG_PATH" >&2
        echo "  DB:       $SP_COCKPIT_AUDIT_DB_PATH" >&2
        echo "  Frontend: $SP_COCKPIT_FRONTEND_DIST" >&2
        echo "  URL:      http://${HOST}:${PORT}" >&2

        exec "$VENV_PYTHON" -m sp_cockpit.main
    fi
done

# ── Docker 模式（默认） ────────────────────────────────
source "$DIR/share/_infra.sh"

SP_COCKPIT_PORT="${SP_COCKPIT_PORT:-9100}"
SP_COCKPIT_ENABLED=true
SP_COCKPIT_RUNNING=false

cleanup() {
    echo "" >&2
    info "正在停止 sp-cockpit..."
    docker compose -f "$COMPOSE_FILE" stop sp-cockpit 2>/dev/null || true
    info "sp-cockpit 已停止。"
}
trap cleanup EXIT INT TERM

infra_start_cockpit

if [ "$SP_COCKPIT_RUNNING" != true ]; then
    die "sp-cockpit 启动失败"
fi

echo "" >&2
echo "════════════════════════════════════════════" >&2
echo "  sp-cockpit 已启动：" >&2
echo "    sp-cockpit  (Docker)  (http://localhost:${SP_COCKPIT_PORT})" >&2
echo "" >&2
echo "  按 Ctrl+C 停止服务" >&2
echo "════════════════════════════════════════════" >&2

# 监控 Docker 服务健康状态
while true; do
    unhealthy=$(docker compose -f "$COMPOSE_FILE" ps --format json \
        | jq -r 'select(.Health == "unhealthy" or .State == "exited") | .Service' 2>/dev/null || true)
    if [ -n "$unhealthy" ]; then
        warn "服务异常: $unhealthy"
        break
    fi
    sleep 5
done
info "某个服务异常退出，正在关闭所有服务..."
