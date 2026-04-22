#!/usr/bin/env bash
# 向量索引构建 — 封装 scripts/build_dense_index.py
#
# 用法:
#   cd dense-deploy && ./scripts/build_index.sh [--repos frameworks/base] [--batch-size 32]
#
# 前置条件: Milvus + Embedding 服务已启动 (docker compose up -d)
set -euo pipefail

DIR=$(cd "$(dirname "$0")/.." && pwd)
PROJ_ROOT=$(cd "$DIR/.." && pwd)

# 加载 .env（项目根优先，dense-deploy 覆盖）
for envfile in "$PROJ_ROOT/.env" "$DIR/.env"; do
    if [ -f "$envfile" ]; then
        set -a
        source "$envfile"
        set +a
    fi
done

# 从 compose 端口映射到 DENSE_* 环境变量
export DENSE_VECTOR_DB_URL="${DENSE_VECTOR_DB_URL:-http://localhost:${MILVUS_PORT:-19530}}"
export DENSE_EMBEDDING_URL="${DENSE_EMBEDDING_URL:-http://localhost:${EMBEDDING_PORT:-8080}/v1}"

# 从 DENSE_EMBEDDING_URL 反推 EMBEDDING_PORT 供 healthcheck 使用
export EMBEDDING_PORT="${EMBEDDING_PORT:-$(echo "$DENSE_EMBEDDING_URL" | sed -n 's|.*://[^:]*:\([0-9]*\).*|\1|p')}"
export DENSE_EMBEDDING_MODEL="${DENSE_EMBEDDING_MODEL:-unixcoder-base}"
export DENSE_EMBEDDING_DIM="${DENSE_EMBEDDING_DIM:-768}"
export DENSE_COLLECTION_NAME="${DENSE_COLLECTION_NAME:-aosp_code}"

# Zoekt 地址（索引构建需要从 Zoekt 获取源码）
export ZOEKT_URL="${ZOEKT_URL:-http://localhost:6070}"

# 健康检查
echo "Checking services..."
"$DIR/scripts/healthcheck.sh"

echo ""
echo "Starting index build..."
PYTHONPATH="$PROJ_ROOT/src" python3 "$PROJ_ROOT/scripts/build_dense_index.py" "$@"
