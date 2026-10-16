#!/bin/sh
# Production process: migrate, then serve. Reload and the debug reloader stay off.
set -eu
cd /app
alembic upgrade head
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${APP_PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"
