#!/usr/bin/env bash
# ==============================================================================
# Container Entrypoint Script for Django Backend
# Guarantees PID 1 signal handoff, DB readiness, and static/migration management
# ==============================================================================

set -euo pipefail

echo "==> [Entrypoint] Initializing Django container..."

# ------------------------------------------------------------------------------
# 1. PostgreSQL Database Readiness Probe (Psycopg SELECT 1 Handshake - 60s Timeout)
# ------------------------------------------------------------------------------
python - << 'EOF'
import os
import sys
import time
import psycopg2

host = os.environ.get("POSTGRES_HOST", "db")
port = int(os.environ.get("POSTGRES_PORT", "5432"))
dbname = os.environ.get("POSTGRES_DB", "django_db")
user = os.environ.get("POSTGRES_USER", "django_user")
password = os.environ.get("POSTGRES_PASSWORD", "")
timeout = 60
start_time = time.time()

print(f"==> [Healthcheck] Verifying PostgreSQL query readiness at {host}:{port}/{dbname} (max {timeout}s)...")

dsn = dict(
    host=host,
    port=port,
    dbname=dbname,
    user=user,
    password=password,
    connect_timeout=2
)

while True:
    try:
        with psycopg2.connect(**dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
        print(f"==> [Healthcheck] PostgreSQL is accepting queries at {host}:{port}!")
        sys.exit(0)
    except Exception as exc:
        elapsed = time.time() - start_time
        if elapsed >= timeout:
            print(f"==> [FATAL] PostgreSQL query readiness failed at {host}:{port} after {timeout}s: {exc}", file=sys.stderr)
            sys.exit(1)
        time.sleep(1)
EOF

# ------------------------------------------------------------------------------
# 2. Collect Static Files & Apply Migrations (Gated by RUN_BOOTSTRAP)
# Avoids concurrent migration races and static manifest corruption across workers.
# ------------------------------------------------------------------------------
RUN_BOOTSTRAP="${RUN_BOOTSTRAP:-1}"

if [ "$RUN_BOOTSTRAP" = "1" ]; then
    echo "==> [Django] Collecting static files..."
    python manage.py collectstatic --no-input

    echo "==> [Django] Applying database migrations..."
    python manage.py migrate --no-input
else
    echo "==> [Entrypoint] Skipping static collection and migrations (RUN_BOOTSTRAP=0)..."
fi

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
