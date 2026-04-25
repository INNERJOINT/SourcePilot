# Dense Deploy — Qdrant + Embedding Service

Docker deployment for the Qdrant vector database and embedding service that power SourcePilot's vector-retrieval feature.

## Quickstart

```bash
cd dense-deploy

# 1. Start services (first-time embedding image build takes a while)
docker compose up -d

# 2. Check service health
./scripts/healthcheck.sh

# 3. Build the vector index — runs inside the containerized dense-indexer
#    (requires AOSP_SOURCE_ROOT in the project root .env — default /mnt/code/ACE)
./scripts/build_index.sh \
    --source-dir /mnt/code/ACE/frameworks/base \
    --repo-name frameworks/base

# 4. Enable the dense backend in SourcePilot
export DENSE_ENABLED=true
```

## 容器内索引（Containerized Indexing）

自 2026-04 起，`build_dense_index.py` 不再直接跑在宿主机；`./scripts/build_index.sh`
已改写为 `docker compose --profile indexer run --rm dense-indexer` 的薄包装层，
自动把 `--source-dir <host path>` 翻译为容器内 `/src/<subpath>`。

```bash
# 一次性构建（默认 profile 不会拉起 indexer）
cd dense-deploy
AOSP_SOURCE_ROOT=/mnt/code/ACE ./scripts/build_index.sh \
    --source-dir /mnt/code/ACE/frameworks/base \
    --repo-name frameworks/base \
    --batch-size 32

# 或直接调用 compose（需把路径手动写成容器内路径 /src/...）
docker compose --profile indexer run --rm dense-indexer \
    --source-dir /src/frameworks/base --repo-name frameworks/base
```

约束：`--source-dir` 必须落在 `$AOSP_SOURCE_ROOT` 下，否则 wrapper 会报错退出
（避免静默索引空内容）。宿主机上无需再安装 `qdrant-client`。

## Service Components

| Service | Port | Description |
|---------|------|-------------|
| Qdrant | 6333 (REST), 6334 (gRPC) | Vector database |
| Embedding Server | 8080 | OpenAI-compatible embedding API |

## Environment Variables

See `.env.example`. Copy and edit it:

```bash
cp .env.example .env
```

Key variables:

- `EMBEDDING_MODEL` — model name (default `microsoft/unixcoder-base`)
- `EMBEDDING_DIM` — vector dimension (default 768)
- `EMBEDDING_PORT` — embedding service port (default 8080)
- `QDRANT_PORT` — Qdrant REST port (default 6333)

## Changing Models

After switching embedding models you **must rebuild the index**, otherwise search results will be incorrect:

```bash
# 1. Update EMBEDDING_MODEL and EMBEDDING_DIM in .env
# 2. Update the MODEL_VERSION file
echo "model=new-model dim=1024" > MODEL_VERSION
# 3. Rebuild the embedding image
docker compose build dense-index-coderankembed
docker compose up -d dense-index-coderankembed
# 4. Drop the old collection and rebuild the index
./scripts/build_index.sh \
    --source-dir /mnt/code/ACE/frameworks/base \
    --repo-name frameworks/base
```

## GPU Support

`docker-compose.yml` reserves NVIDIA GPU resources by default. If you have no GPU, comment out the `deploy.resources` block to run on CPU.

## Integrating with SourcePilot

After the services are up, set in the SourcePilot environment:

```bash
export DENSE_ENABLED=true
export DENSE_VECTOR_DB_URL=http://localhost:6333
export DENSE_EMBEDDING_URL=http://localhost:8080/v1
```
