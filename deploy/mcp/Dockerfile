# MCP Server — Streamable HTTP transport container (mcp-server/).
# Build context is the repository root (see deploy/docker-compose.yml).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/mcp-server

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY mcp-server/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY mcp-server/ /app/mcp-server/

EXPOSE 8888
CMD ["python", "-m", "mcp_server", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8888"]
