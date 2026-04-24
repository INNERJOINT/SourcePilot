#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
#  AOSP Code Search 开发模式启动脚本
#
#  基础设施（zoekt/milvus/neo4j）通过 Docker 启动，
#  应用服务（SourcePilot/MCP/sp-cockpit）以裸进程运行，
#  修改代码后无需重建镜像即可验证。
#
#  用法：
#    ./run_all_dev.sh                           # 使用 .env 配置
#    DENSE_ENABLED=true ./run_all_dev.sh        # 包含 Dense 检索栈
#    STRUCTURAL_ENABLED=true ./run_all_dev.sh        # 包含 Neo4j 结构化检索
# ──────────────────────────────────────────────────────

set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)

# 加载共享库
source "$DIR/share/_common.sh"
_common_parse_help "$@"
source "$DIR/share/_env.sh"
source "$DIR/share/_infra.sh"

# ── 配置 ──────────────────────────────────────────────
ZOEKT_URL="${ZOEKT_URL:-http://localhost:6070}"
MCP_PORT="${MCP_PORT:-8888}"
SP_COCKPIT_PORT="${SP_COCKPIT_PORT:-9100}"
SP_COCKPIT_ENABLED="${SP_COCKPIT_ENABLED:-true}"

# ── pyenv 虚拟环境 ────────────────────────────────────
VENV_PYTHON="/opt/pyenv/versions/dify_py3_env/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
    warn "$VENV_PYTHON not found, using system python3"
    VENV_PYTHON="python3"
fi

# ── 进程管理 ──────────────────────────────────────────
PIDS=()
ZOEKT_PIDS=()
ZOEKT_DOCKER=false
SP_COCKPIT_RUNNING=false

cleanup() {
    echo "" >&2
    info "正在停止所有服务..."
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
    info "所有服务已停止。"
}
trap cleanup EXIT INT TERM

# ── 1a. 启动多项目 zoekt-webserver（按 projects.yaml）──
_projects_cfg="${PROJECTS_CONFIG_PATH:-$PROJ_ROOT/config/projects.yaml}"

if [ -f "$_projects_cfg" ]; then
    # 用内联 Python 从 YAML 提取 (index_dir, zoekt_url) 对，每行一个
    _zoekt_entries=$("$VENV_PYTHON" - "$_projects_cfg" <<'EOF'
import sys, re

cfg = open(sys.argv[1]).read()

# 简单逐行状态机，不依赖 PyYAML
projects = []
cur = {}
for line in cfg.splitlines():
    stripped = line.strip()
    if stripped.startswith('- name:'):
        if cur:
            projects.append(cur)
        cur = {}
    for key in ('index_dir', 'zoekt_url'):
        m = re.match(rf'\s*{key}:\s*(.+)', line)
        if m:
            cur[key] = m.group(1).strip()
if cur:
    projects.append(cur)

for p in projects:
    idx = p.get('index_dir', '')
    url = p.get('zoekt_url', 'http://localhost:6070')
    port = re.search(r':(\d+)$', url)
    port = port.group(1) if port else '6070'
    if idx:
        print(f"{idx}|{port}")
EOF
    )

    _project_count=$(echo "$_zoekt_entries" | grep -c '|' || true)
    if [ "${_project_count:-0}" -gt 1 ]; then
        info "多项目模式：发现 $_project_count 个项目，逐一启动 zoekt-webserver"
        while IFS='|' read -r _idx _port; do
            [ -z "$_idx" ] && continue
            if curl -sf "http://localhost:${_port}/" >/dev/null 2>&1; then
                info "zoekt-webserver 已在运行 (port $_port, index: $_idx)，跳过启动"
                ZOEKT_DOCKER=true
                continue
            fi
            if [ ! -d "$_idx" ]; then
                warn "index_dir 不存在: $_idx（跳过 port $_port）"
                continue
            fi
            info "启动 zoekt-webserver (index: $_idx, port: $_port)..."
            zoekt-webserver -index "$_idx" -listen ":$_port" &
            _zpid=$!
            PIDS+=($_zpid)
            ZOEKT_PIDS+=($_zpid)
            info "  zoekt-webserver PID $_zpid 监听 :$_port"
            for i in $(seq 1 "$MAX_RETRIES"); do
                if curl -sf "http://localhost:${_port}/" >/dev/null 2>&1; then
                    info "  zoekt-webserver (port $_port) 就绪"
                    break
                fi
                [ "$i" -eq "$MAX_RETRIES" ] && warn "  zoekt-webserver (port $_port) 启动超时"
                sleep 1
            done
        done <<< "$_zoekt_entries"
    else
        # 单项目：使用标准 infra_start_zoekt（兼容旧行为）
        infra_start_zoekt
    fi
else
    # 无配置文件：回退单项目模式
    infra_start_zoekt
fi

# ── 1b. 启动 Dense / Structural 基础设施 (Docker) ─────────
infra_start_dense
infra_start_structural

# ── 2. 启动 SourcePilot (裸进程, --reload) ───────────
SP_PID=""
if curl -sf http://localhost:9000/api/health >/dev/null 2>&1; then
    info "检测到 SourcePilot 已在运行 (port 9000)，跳过启动"
else
    export AUDIT_LOG_FILE="${AUDIT_LOG_FILE:-$PROJ_ROOT/audit.log}"
    info "启动 SourcePilot (bare, port 9000, --reload)..."
    env PYTHONPATH="$PROJ_ROOT/src" \
        "$VENV_PYTHON" -m uvicorn app:app --host 0.0.0.0 --port 9000 --reload &
    PIDS+=($!)
    SP_PID=${PIDS[-1]}

    for i in $(seq 1 "$MAX_RETRIES"); do
        if curl -sf http://localhost:9000/api/health >/dev/null 2>&1; then
            info "SourcePilot 就绪 (PID $SP_PID, --reload)"
            break
        fi
        [ "$i" -eq "$MAX_RETRIES" ] && die "SourcePilot 启动超时 (${MAX_RETRIES}s)"
        sleep 1
    done
fi

# ── 3. 启动 MCP Server (裸进程) ──────────────────────
export SOURCEPILOT_URL="http://localhost:9000"

MCP_PID=""
if curl -sf "http://localhost:${MCP_PORT}/health" >/dev/null 2>&1; then
    info "检测到 MCP Server 已在运行 (port ${MCP_PORT})，跳过启动"
else
    info "启动 MCP Server (bare, streamable-http, port ${MCP_PORT})..."
    env PYTHONPATH="$PROJ_ROOT/mcp-server" \
        "$VENV_PYTHON" -m mcp_server --transport streamable-http --host 0.0.0.0 --port "$MCP_PORT" &
    PIDS+=($!)
    MCP_PID=${PIDS[-1]}

    for i in $(seq 1 "$MAX_RETRIES"); do
        if curl -sf "http://localhost:${MCP_PORT}/health" >/dev/null 2>&1; then
            info "MCP Server 就绪 (PID $MCP_PID)"
            break
        fi
        [ "$i" -eq "$MAX_RETRIES" ] && die "MCP Server 启动超时 (${MAX_RETRIES}s)"
        sleep 1
    done
fi

# ── 4. 启动 sp-cockpit (裸进程) ──────────────────────
SP_COCKPIT_PID=""
if [ "$SP_COCKPIT_ENABLED" = "true" ]; then
    if curl -sf "http://localhost:${SP_COCKPIT_PORT}/api/health" >/dev/null 2>&1; then
        info "检测到 sp-cockpit 已在运行 (port ${SP_COCKPIT_PORT})，跳过启动"
        SP_COCKPIT_RUNNING=true
    else
        export SP_COCKPIT_AUDIT_LOG_PATH="${SP_COCKPIT_AUDIT_LOG_PATH:-$PROJ_ROOT/audit.log}"
        export SP_COCKPIT_AUDIT_DB_PATH="${SP_COCKPIT_AUDIT_DB_PATH:-$PROJ_ROOT/sp-cockpit/data/audit.db}"
        export SP_COCKPIT_HOST="${SP_COCKPIT_HOST:-0.0.0.0}"
        export SP_COCKPIT_PORT="$SP_COCKPIT_PORT"
        export SP_COCKPIT_FRONTEND_DIST="${SP_COCKPIT_FRONTEND_DIST:-$PROJ_ROOT/sp-cockpit/frontend/dist}"

        [ -f "$SP_COCKPIT_AUDIT_LOG_PATH" ] || touch "$SP_COCKPIT_AUDIT_LOG_PATH"
        mkdir -p "$(dirname "$SP_COCKPIT_AUDIT_DB_PATH")"

        info "启动 sp-cockpit (bare, port ${SP_COCKPIT_PORT})..."
        (cd "$PROJ_ROOT/sp-cockpit" && env PYTHONPATH="$PROJ_ROOT/sp-cockpit" \
            "$VENV_PYTHON" -m sp_cockpit.main) &
        PIDS+=($!)
        SP_COCKPIT_PID=${PIDS[-1]}

        for i in $(seq 1 "$MAX_RETRIES"); do
            if curl -sf "http://localhost:${SP_COCKPIT_PORT}/api/health" >/dev/null 2>&1; then
                info "sp-cockpit 就绪 (PID $SP_COCKPIT_PID)"
                SP_COCKPIT_RUNNING=true
                break
            fi
            [ "$i" -eq "$MAX_RETRIES" ] && warn "sp-cockpit 启动超时 (${MAX_RETRIES}s)，继续运行其他服务"
            sleep 1
        done
    fi
fi

# ── 启动完成 ──────────────────────────────────────────
echo "" >&2
echo "════════════════════════════════════════════" >&2
echo "  开发模式 — 所有服务已启动：" >&2
if [ "$ZOEKT_DOCKER" = true ]; then
echo "    zoekt-webserver  (Docker)          ($ZOEKT_URL)" >&2
else
echo "    zoekt-webserver  PID ${PIDS[0]:-?}     ($ZOEKT_URL)" >&2
fi
if [ "${DENSE_ENABLED:-false}" = "true" ]; then
echo "    Dense 检索栈     (Docker)          (Qdrant :6333)" >&2
fi
if [ "${STRUCTURAL_ENABLED:-false}" = "true" ]; then
echo "    Neo4j            (Docker)          (bolt://localhost:7687)" >&2
fi
if [ -n "$SP_PID" ]; then
echo "    SourcePilot      PID $SP_PID (bare, --reload)  (http://localhost:9000)" >&2
else
echo "    SourcePilot      (already running)              (http://localhost:9000)" >&2
fi
if [ -n "$MCP_PID" ]; then
echo "    MCP Server       PID $MCP_PID (bare)            (http://0.0.0.0:${MCP_PORT}/mcp)" >&2
else
echo "    MCP Server       (already running)              (http://0.0.0.0:${MCP_PORT}/mcp)" >&2
fi
if [ "$SP_COCKPIT_ENABLED" = "true" ]; then
    if [ -n "$SP_COCKPIT_PID" ]; then
        echo "    sp-cockpit       PID $SP_COCKPIT_PID (bare)   (http://localhost:${SP_COCKPIT_PORT})" >&2
    elif [ "$SP_COCKPIT_RUNNING" = true ]; then
        echo "    sp-cockpit       (already running)              (http://localhost:${SP_COCKPIT_PORT})" >&2
    else
        echo "    sp-cockpit       (启动失败/超时)" >&2
    fi
fi
echo "" >&2
echo "  SourcePilot 已启用 --reload，修改 src/ 代码会自动重载" >&2
echo "  按 Ctrl+C 停止所有服务" >&2
echo "════════════════════════════════════════════" >&2

# 等待任意子进程退出
wait -n 2>/dev/null || true
info "某个服务异常退出，正在关闭所有服务..."
