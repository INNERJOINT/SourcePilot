# Dense Deploy — Milvus + Embedding 服务部署

为 SourcePilot 的向量检索功能提供 Milvus 向量数据库和 embedding 服务的 Docker 部署。

## 快速启动

```bash
cd dense-deploy

# 1. 启动服务（首次构建 embedding 镜像需要较长时间）
docker compose up -d

# 2. 检查服务状态
./scripts/healthcheck.sh

# 3. 构建向量索引（需要 Zoekt 服务运行中）
ZOEKT_URL=http://localhost:6070 ./scripts/build_index.sh --repos frameworks/base

# 4. 在 SourcePilot 中启用 dense 后端
export DENSE_ENABLED=true
```

## 服务组件

| 服务 | 端口 | 说明 |
|------|------|------|
| Milvus | 19530 (gRPC), 9091 (REST) | 向量数据库 |
| Embedding Server | 8080 | OpenAI-compatible embedding API |
| MinIO | 9000, 9001 (console) | Milvus 对象存储后端 |
| etcd | 2379 | Milvus 元数据存储 |

## 环境变量

参见 `.env.example`。复制并修改：

```bash
cp .env.example .env
```

主要变量：

- `EMBEDDING_MODEL` — 模型名称（默认 `microsoft/unixcoder-base`）
- `EMBEDDING_DIM` — 向量维度（默认 768）
- `EMBEDDING_PORT` — embedding 服务端口（默认 8080）
- `MILVUS_PORT` — Milvus gRPC 端口（默认 19530）

## 更换模型

更换 embedding 模型后**必须重建索引**，否则搜索结果将不正确：

```bash
# 1. 修改 .env 中的 EMBEDDING_MODEL 和 EMBEDDING_DIM
# 2. 更新 MODEL_VERSION 文件
echo "model=new-model dim=1024" > MODEL_VERSION
# 3. 重建 embedding 镜像
docker compose build embedding-server
docker compose up -d embedding-server
# 4. 清空旧 collection 并重建索引
./scripts/build_index.sh --repos frameworks/base
```

## GPU 支持

docker-compose.yml 默认配置了 NVIDIA GPU 资源预留。如果没有 GPU，注释掉 `deploy.resources` 段即可使用 CPU 运行。

## 与 SourcePilot 集成

服务启动后，在 SourcePilot 环境中设置：

```bash
export DENSE_ENABLED=true
export DENSE_VECTOR_DB_URL=http://localhost:19530
export DENSE_EMBEDDING_URL=http://localhost:8080/v1
```
