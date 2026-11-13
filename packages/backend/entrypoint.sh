#!/usr/bin/env bash
set -euo pipefail

# Entrypoint for the backend Docker image.
# Override SERVICE_TYPE to run a different process profile from the same image.
#
# Profiles:
#   web     — Uvicorn ASGI server (default)
#   worker  — Django tasks database worker (processes @task enqueued work)
#   beat    — Celery worker + beat scheduler (periodic tasks only)
#   migrate — Run migrations + collectstatic, then exit

SERVICE_TYPE="${SERVICE_TYPE:-web}"

case "$SERVICE_TYPE" in
  web)
    exec uvicorn config.asgi:application \
      --host 0.0.0.0 \
      --port "${PORT:-8000}" \
      --proxy-headers \
      --forwarded-allow-ips "*"
    ;;
  worker)
    exec python manage.py db_worker
    ;;
  beat)
    exec celery -A config worker \
      --beat \
      --loglevel=info \
      --concurrency="${CELERY_CONCURRENCY:-2}"
    ;;
  migrate)
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
    ;;
  *)
    echo "Unknown SERVICE_TYPE: $SERVICE_TYPE" >&2
    echo "Valid: web, worker, beat, migrate" >&2
    exit 1
    ;;
esac
