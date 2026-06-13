# syntax=docker/dockerfile:1.7
# IAMS backend — multi-stage production-shaped image.
#
# Stage 1 (builder): installs dependencies into /app/.venv
# Stage 2 (runtime):  copies the venv + source, runs as a non-root user,
#                     entrypoint script handles migrations + collectstatic,
#                     gunicorn serves the WSGI app behind nginx.
#
# Build with:
#   docker build -t iams-backend:latest .
#
# Run with:
#   docker run --env-file .env -p 8000:8000 iams-backend:latest

# ─────────────────────────────────────────────────────────────────────
# Builder stage
# ─────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# System build deps for psycopg2 + weasyprint
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv==0.5.13

# Resolve & install deps (cache-friendly layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ─────────────────────────────────────────────────────────────────────
# Runtime stage
# ─────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    PORT=8000

# Runtime libs only (no compilers)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        shared-mime-info \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd --system --gid 1000 iams \
    && useradd --system --uid 1000 --gid iams --home /app --shell /sbin/nologin iams

WORKDIR /app

# Copy virtualenv from builder
COPY --from=builder --chown=iams:iams /app/.venv /app/.venv

# Copy app source
COPY --chown=iams:iams . /app/

# Copy entrypoint
COPY --chown=iams:iams docker/entrypoint.sh /usr/local/bin/iams-entrypoint
RUN chmod +x /usr/local/bin/iams-entrypoint

# Static files target dir (writable by app user). Also make the /app
# working directory itself iams-owned: gunicorn's control server creates a
# ``.gunicorn`` dir in the cwd, which fails with EACCES when /app is the
# root-owned WORKDIR (the COPY --chown only owns the contents, not the dir).
RUN mkdir -p /app/staticfiles /app/media \
    && chown iams:iams /app \
    && chown -R iams:iams /app/staticfiles /app/media

USER iams

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:${PORT}/health/ || exit 1

# tini PID 1 → graceful signal handling for gunicorn workers
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/iams-entrypoint"]

# Default: web server. Override for celery worker / beat in compose.
#   web:    gunicorn (default)
#   worker: celery -A config worker -l info
#   beat:   celery -A config beat -l info -S django
CMD ["web"]
