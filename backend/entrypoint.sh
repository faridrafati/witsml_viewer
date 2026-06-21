#!/usr/bin/env bash
# Run DB migrations (best-effort), seed, then serve the API.
set -e

echo "[entrypoint] Running alembic migrations..."
alembic upgrade head || echo "[entrypoint] WARN: alembic upgrade failed (continuing; tables will be created on startup)."

echo "[entrypoint] Seeding parameter catalog / units / super-admin..."
python -m app.db.seed || echo "[entrypoint] WARN: seed step failed (continuing)."

echo "[entrypoint] Starting uvicorn on ${API_HOST:-0.0.0.0}:${API_PORT:-8000}..."
exec uvicorn app.main:app --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}"
