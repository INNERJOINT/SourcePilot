# Graph indexer — one-shot container that runs scripts/build_graph_index.py
# Build context is the repository root (see deploy/docker-compose.yml).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir \
        "neo4j>=5,<6" \
        "tree-sitter>=0.21" \
        tree-sitter-java \
        tree-sitter-cpp \
        tree-sitter-python

# build_graph_index.py is self-contained — no src/ imports needed.
COPY scripts/indexing/build_graph_index.py /app/scripts/build_graph_index.py

ENTRYPOINT ["python3", "/app/scripts/build_graph_index.py"]
