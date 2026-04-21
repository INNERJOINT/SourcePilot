# Dense Deploy — Milvus + Embedding Service

Docker deployment for the Milvus vector database and embedding service that power SourcePilot's vector-retrieval feature.

## Quickstart

```bash
cd dense-deploy

# 1. Start services (first-time embedding image build takes a while)
docker compose up -d

# 2. Check service health
./scripts/healthcheck.sh

# 3. Build the vector index (requires a running Zoekt service)
ZOEKT_URL=http://localhost:6070 ./scripts/build_index.sh --repos frameworks/base

# 4. Enable the dense backend in SourcePilot
export DENSE_ENABLED=true
```

## Service Components

| Service | Port | Description |
|---------|------|-------------|
| Milvus | 19530 (gRPC), 9091 (REST) | Vector database |
| Embedding Server | 8080 | OpenAI-compatible embedding API |
| MinIO | 9000, 9001 (console) | Milvus object-storage backend |
| etcd | 2379 | Milvus metadata store |

## Environment Variables

See `.env.example`. Copy and edit it:

```bash
cp .env.example .env
```

Key variables:

- `EMBEDDING_MODEL` — model name (default `microsoft/unixcoder-base`)
- `EMBEDDING_DIM` — vector dimension (default 768)
- `EMBEDDING_PORT` — embedding service port (default 8080)
- `MILVUS_PORT` — Milvus gRPC port (default 19530)

## Changing Models

After switching embedding models you **must rebuild the index**, otherwise search results will be incorrect:

```bash
# 1. Update EMBEDDING_MODEL and EMBEDDING_DIM in .env
# 2. Update the MODEL_VERSION file
echo "model=new-model dim=1024" > MODEL_VERSION
# 3. Rebuild the embedding image
docker compose build embedding-server
docker compose up -d embedding-server
# 4. Drop the old collection and rebuild the index
./scripts/build_index.sh --repos frameworks/base
```

## GPU Support

`docker-compose.yml` reserves NVIDIA GPU resources by default. If you have no GPU, comment out the `deploy.resources` block to run on CPU.

## Integrating with SourcePilot

After the services are up, set in the SourcePilot environment:

```bash
export DENSE_ENABLED=true
export DENSE_VECTOR_DB_URL=http://localhost:19530
export DENSE_EMBEDDING_URL=http://localhost:8080/v1
```
