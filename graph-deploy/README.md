# Graph Deploy — Neo4j 图数据库

Docker 单节点部署，为 SourcePilot 的图谱检索功能（GraphRAG Lane）提供 Neo4j 后端。

## 快速启动

```bash
cd graph-deploy

# 1. 启动 Neo4j（首次拉取镜像需要一点时间）
docker compose up -d

# 2. 验证服务健康
docker compose ps
docker compose logs neo4j | tail -20

# 3. 浏览器访问 Neo4j Browser（可选）
open http://localhost:7474
# 用户名: neo4j  密码: sourcepilot
```

## 服务组件

| 服务   | 端口       | 说明                         |
|--------|------------|------------------------------|
| Neo4j  | 7474 (HTTP) | Neo4j Browser / REST API     |
| Neo4j  | 7687 (Bolt) | Bolt 协议（驱动连接）        |

## 连接信息

与 `.env` 默认值对应：

```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=sourcepilot
```

## 内存说明

默认配置适合开发/测试环境：

- Heap 初始: 512M，最大: 2G
- Page Cache: 512M
- **建议宿主机 4GB+ 系统内存**
- 索引 `frameworks/base` 子集（`build_graph_index.py`）约消耗 1–2GB Neo4j heap

如需调整，修改 `docker-compose.yml` 中的 `NEO4J_server_memory_*` 变量后重启服务。

## 构建图谱索引

```bash
# 在 Neo4j 启动并健康后，运行索引脚本
cd /mnt/code/T2/Dify
PYTHONPATH=src python scripts/build_graph_index.py --repos frameworks/base
```

## 备份

```bash
# 导出数据库快照
docker compose exec neo4j neo4j-admin database dump neo4j --to-path=/backups
```

## 重建索引

```bash
# 1. 停服务，清除数据卷
docker compose down -v

# 2. 重新启动
docker compose up -d

# 3. 等待健康检查通过后重新索引
PYTHONPATH=src python scripts/build_graph_index.py --repos frameworks/base
```

## APOC 插件

已通过 `NEO4J_PLUGINS='["apoc"]'` 自动安装 APOC 插件，支持图算法、批量导入等高级操作。
