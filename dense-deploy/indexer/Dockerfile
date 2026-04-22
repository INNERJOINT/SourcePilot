# Dense indexer — one-shot container that runs scripts/build_dense_index.py
# Build context is the repository root (see dense-deploy/docker-compose.yml).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Reuse src/ deps (httpx, starlette, neo4j, tree-sitter, ...) and add pymilvus for dense.
COPY src/requirements.txt /tmp/src-requirements.txt
RUN pip install --no-cache-dir -r /tmp/src-requirements.txt \
    && pip install --no-cache-dir "pymilvus>=2.4,<3"

COPY src/ /app/src/
COPY scripts/build_dense_index.py /app/scripts/build_dense_index.py

ENTRYPOINT ["python3", "/app/scripts/build_dense_index.py"]
