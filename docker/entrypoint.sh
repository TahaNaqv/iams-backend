#!/usr/bin/env sh
# IAMS backend container entrypoint.
#
# Dispatches based on the first arg:
#   web      → gunicorn (default)
#   worker   → celery worker
#   beat     → celery beat scheduler
#   flower   → celery flower monitoring UI
#   migrate  → run migrations and exit (init container pattern)
#   shell    → drop into Django shell
#   manage   → run an arbitrary `manage.py` subcommand
#
# Environment variables:
#   GUNICORN_WORKERS         — number of gunicorn worker procs (default: CPU * 2 + 1)
#   GUNICORN_THREADS         — threads per worker (default: 2)
#   GUNICORN_TIMEOUT         — request timeout in seconds (default: 60)
#   GUNICORN_MAX_REQUESTS    — restart workers after N requests (default: 1000)
#   DJANGO_COLLECTSTATIC     — set to "1" to run collectstatic on web start
#   DJANGO_AUTO_MIGRATE      — set to "1" to run migrate before serving (dev/staging only)
set -eu

CMD="${1:-web}"
shift || true

case "${CMD}" in
  web)
    if [ "${DJANGO_AUTO_MIGRATE:-0}" = "1" ]; then
      echo "[entrypoint] running migrations..."
      python manage.py migrate --noinput
    fi
    if [ "${DJANGO_COLLECTSTATIC:-1}" = "1" ]; then
      echo "[entrypoint] collecting static files..."
      python manage.py collectstatic --noinput --clear
    fi
    WORKERS="${GUNICORN_WORKERS:-$(python -c 'import multiprocessing as m; print(max(2, m.cpu_count()*2+1))')}"
    THREADS="${GUNICORN_THREADS:-2}"
    TIMEOUT="${GUNICORN_TIMEOUT:-60}"
    MAX_REQUESTS="${GUNICORN_MAX_REQUESTS:-1000}"
    MAX_REQUESTS_JITTER="${GUNICORN_MAX_REQUESTS_JITTER:-100}"
    echo "[entrypoint] starting gunicorn (workers=${WORKERS}, threads=${THREADS})"
    exec gunicorn config.wsgi:application \
        --bind "0.0.0.0:${PORT:-8000}" \
        --workers "${WORKERS}" \
        --threads "${THREADS}" \
        --worker-class gthread \
        --timeout "${TIMEOUT}" \
        --graceful-timeout 30 \
        --keep-alive 5 \
        --max-requests "${MAX_REQUESTS}" \
        --max-requests-jitter "${MAX_REQUESTS_JITTER}" \
        --access-logfile - \
        --error-logfile - \
        --log-level info \
        --capture-output
    ;;
  worker)
    echo "[entrypoint] starting celery worker"
    exec celery -A config worker \
        --loglevel "${CELERY_LOG_LEVEL:-INFO}" \
        --concurrency "${CELERY_CONCURRENCY:-4}" \
        --max-tasks-per-child "${CELERY_MAX_TASKS_PER_CHILD:-500}"
    ;;
  beat)
    echo "[entrypoint] starting celery beat scheduler"
    exec celery -A config beat \
        --loglevel "${CELERY_LOG_LEVEL:-INFO}" \
        --scheduler django_celery_beat.schedulers:DatabaseScheduler
    ;;
  flower)
    echo "[entrypoint] starting flower (celery monitoring UI)"
    exec celery -A config flower --port="${FLOWER_PORT:-5555}"
    ;;
  migrate)
    echo "[entrypoint] running migrations only"
    exec python manage.py migrate --noinput
    ;;
  shell)
    exec python manage.py shell
    ;;
  manage)
    exec python manage.py "$@"
    ;;
  *)
    # Treat anything else as a raw command (escape hatch)
    exec "${CMD}" "$@"
    ;;
esac
