#!/usr/bin/env bash
set -euo pipefail

cd /app

echo "→ Running database migrations (alembic upgrade head)"
max_attempts=12
attempt=1
until alembic upgrade head; do
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "✗ Migrations failed after ${max_attempts} attempts"
    exit 1
  fi
  echo "… migration attempt ${attempt} failed, retrying in 10s (RDS may still be starting or SG updating)"
  attempt=$((attempt + 1))
  sleep 10
done

echo "→ Starting contenthub-api"
exec python3 -m uvicorn main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --app-dir /app/src
