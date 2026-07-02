#!/usr/bin/env bash
set -euo pipefail

echo "Running alembic upgrade head..."
alembic -c backend/alembic.ini upgrade head

echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
