#!/usr/bin/env bash
# 触发 zoekt 索引重建
# 用法: ./scripts/reindex.sh
#
# Cron 示例 (每天凌晨 3 点重建):
#   0 3 * * * cd /path/to/project && ./scripts/reindex.sh >> /var/log/zoekt-reindex.log 2>&1
#
# 自定义仓库路径:
#   ZOEKT_REPO_PATH=/other/repo ./scripts/reindex.sh

set -euo pipefail
DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$DIR"

# 加载 .env 配置（如果存在）
if [ -f "$DIR/.env" ]; then
    source "$DIR/scripts/_env.sh"
fi

REPO_PATH="${ZOEKT_REPO_PATH:-/mnt/code/ACE/.repo}"
if [ ! -d "$REPO_PATH" ]; then
    echo "Error: 仓库路径不存在: $REPO_PATH" >&2
    echo "请设置 ZOEKT_REPO_PATH 环境变量或在 .env 中配置" >&2
    exit 1
fi

echo "开始索引重建 (repo: $REPO_PATH)..." >&2
docker compose run --rm zoekt-indexserver
echo "索引重建完成: $(date)" >&2
