# SourcePilot gateway — HTTP API container (src/app.py).
# Build context is the repository root (see deploy/docker-compose.yml).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY src/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Dense lane is optional; add qdrant-client only when explicitly requested.
ARG INSTALL_DENSE=false
RUN if [ "$INSTALL_DENSE" = "true" ]; then pip install --no-cache-dir "qdrant-client>=1.12,<2"; fi

COPY src/ /app/src/

EXPOSE 9000
CMD ["python", "-m", "uvicorn", "--app-dir", "/app/src", "app:app", "--host", "0.0.0.0", "--port", "9000"]
