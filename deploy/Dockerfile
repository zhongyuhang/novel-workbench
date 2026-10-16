# Production image: built frontend plus the FastAPI process. No reload.
FROM node:22-bookworm-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
RUN useradd --create-home --uid 10001 --shell /bin/sh appuser \
    && mkdir -p /data/backups \
    && chown appuser:appuser /data /data/backups

WORKDIR /app
COPY backend/pyproject.toml backend/README.md backend/alembic.ini ./
COPY backend/app ./app
COPY backend/alembic ./alembic
RUN pip install --no-cache-dir .
COPY --from=frontend /src/frontend/dist /app/frontend/dist
COPY deploy/entrypoint.sh /app/entrypoint.sh
RUN chmod 755 /app/entrypoint.sh && chown -R appuser:appuser /app

USER appuser
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    DATA_DIR=/data \
    FRONTEND_DIST=/app/frontend/dist
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')"]
ENTRYPOINT ["/app/entrypoint.sh"]
