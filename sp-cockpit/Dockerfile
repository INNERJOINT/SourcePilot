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
COPY sp_cockpit ./sp_cockpit
COPY --from=frontend /app/frontend/dist ./frontend/dist

ENV SP_COCKPIT_AUDIT_LOG_PATH=/data/audit.log \
    SP_COCKPIT_AUDIT_DB_PATH=/data/audit.db \
    SP_COCKPIT_PORT=9100 \
    SP_COCKPIT_FRONTEND_DIST=/app/frontend/dist \
    SP_COCKPIT_HOST=0.0.0.0

EXPOSE 9100
CMD ["python", "-m", "sp_cockpit.main"]
