# Multi-stage build: frontend → python runtime
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS runtime
WORKDIR /app
RUN pip install --no-cache-dir fastapi 'uvicorn[standard]' pydantic
COPY pyproject.toml ./
COPY audit_viewer ./audit_viewer
COPY --from=frontend /app/frontend/dist ./frontend/dist

ENV AUDIT_LOG_PATH=/data/audit.log \
    AUDIT_DB_PATH=/data/audit.db \
    AUDIT_VIEWER_PORT=9100 \
    AUDIT_VIEWER_FRONTEND_DIST=/app/frontend/dist \
    AUDIT_VIEWER_HOST=0.0.0.0

EXPOSE 9100
CMD ["python", "-m", "audit_viewer.main"]
