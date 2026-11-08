#!/usr/bin/env bash
# ==============================================================================
# Container Entrypoint Script for Django Backend
# Guarantees PID 1 signal handoff, DB readiness, and static/migration management
# ==============================================================================

set -euo pipefail

echo "==> [Entrypoint] Initializing Django container..."

# ------------------------------------------------------------------------------
# 1. PostgreSQL Database Readiness Probe (Python Socket Check - 60s Timeout)
# ------------------------------------------------------------------------------
DB_HOST="${POSTGRES_HOST:-db}"
DB_PORT="${POSTGRES_PORT:-5432}"

python - << 'EOF'
import socket
import time
import os
import sys

host = os.environ.get("POSTGRES_HOST", "db")
port = int(os.environ.get("POSTGRES_PORT", "5432"))
timeout = 60
start_time = time.time()

print(f"==> [Healthcheck] Probing PostgreSQL socket at {host}:{port} (max {timeout}s)...")

while True:
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"==> [Healthcheck] PostgreSQL is reachable at {host}:{port}!")
            sys.exit(0)
    except (socket.timeout, ConnectionRefusedError, OSError) as exc:
        elapsed = time.time() - start_time
        if elapsed >= timeout:
            print(f"==> [FATAL] Timed out waiting for PostgreSQL ({host}:{port}) after {timeout}s: {exc}", file=sys.stderr)
            sys.exit(1)
        time.sleep(1)
EOF

# ------------------------------------------------------------------------------
# 2. Collect Static Files (Production Assets)
# ------------------------------------------------------------------------------
echo "==> [Django] Collecting static files..."
python manage.py collectstatic --no-input

# ------------------------------------------------------------------------------
# 3. Apply Committed Database Migrations
# Note: 'makemigrations' is strictly prohibited here per AI Guardrails.
# ------------------------------------------------------------------------------
echo "==> [Django] Applying database migrations..."
python manage.py migrate --no-input

# ------------------------------------------------------------------------------
# 4. Handoff to PID 1 Application Process
# Use 'exec' so the target process replaces this shell and receives OS signals.
# ------------------------------------------------------------------------------
echo "==> [Entrypoint] Starting application process with exec..."

if [ $# -eq 0 ]; then
    exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120
else
    exec "$@"
fi
