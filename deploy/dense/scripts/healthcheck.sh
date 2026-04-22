#!/usr/bin/env bash
# 健康检查：Milvus + Embedding 服务
set -euo pipefail

MILVUS_HOST="${MILVUS_HOST:-localhost}"
MILVUS_HEALTH_PORT="${MILVUS_HEALTH_PORT:-9091}"
EMBEDDING_HOST="${EMBEDDING_HOST:-localhost}"
EMBEDDING_PORT="${EMBEDDING_PORT:-8080}"

DIR=$(cd "$(dirname "$0")/.." && pwd)
ERRORS=0

# 1. Milvus 健康检查
echo "Checking Milvus at ${MILVUS_HOST}:${MILVUS_HEALTH_PORT}..."
if curl -sf "http://${MILVUS_HOST}:${MILVUS_HEALTH_PORT}/healthz" >/dev/null 2>&1; then
    echo "  ✓ Milvus healthy"
else
    echo "  ✗ Milvus unreachable"
    ERRORS=$((ERRORS + 1))
fi

# 2. Embedding 服务健康检查（缓存响应供 MODEL_VERSION 校验复用）
echo "Checking Embedding at ${EMBEDDING_HOST}:${EMBEDDING_PORT}..."
HEALTH_JSON=$(curl -sf "http://${EMBEDDING_HOST}:${EMBEDDING_PORT}/health" 2>/dev/null || echo "")
if [ -n "$HEALTH_JSON" ]; then
    echo "  ✓ Embedding server healthy"
else
    echo "  ✗ Embedding server unreachable"
    ERRORS=$((ERRORS + 1))
fi

# 3. MODEL_VERSION 交叉校验
if [ -f "$DIR/MODEL_VERSION" ] && [ -n "$HEALTH_JSON" ]; then
    EXPECTED_MODEL=$(grep -oP 'model=\K\S+' "$DIR/MODEL_VERSION")
    EXPECTED_DIM=$(grep -oP 'dim=\K\S+' "$DIR/MODEL_VERSION")
    ACTUAL_MODEL=$(echo "$HEALTH_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('model',''))" 2>/dev/null || echo "")
    ACTUAL_DIM=$(echo "$HEALTH_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('dim',''))" 2>/dev/null || echo "")

    if [ -n "$ACTUAL_MODEL" ] && echo "$ACTUAL_MODEL" | grep -q "$EXPECTED_MODEL"; then
        echo "  ✓ Model matches: $EXPECTED_MODEL"
    elif [ -n "$ACTUAL_MODEL" ]; then
        echo "  ✗ Model mismatch: expected *$EXPECTED_MODEL*, got $ACTUAL_MODEL"
        ERRORS=$((ERRORS + 1))
    fi

    if [ "$ACTUAL_DIM" = "$EXPECTED_DIM" ]; then
        echo "  ✓ Dimension matches: $EXPECTED_DIM"
    elif [ -n "$ACTUAL_DIM" ]; then
        echo "  ✗ Dimension mismatch: expected $EXPECTED_DIM, got $ACTUAL_DIM"
        ERRORS=$((ERRORS + 1))
    fi
fi

if [ "$ERRORS" -gt 0 ]; then
    echo "Health check failed with $ERRORS error(s)"
    exit 1
fi

echo "All checks passed."
