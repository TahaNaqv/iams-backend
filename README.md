# IAMS Backend

Internal Audit Management System - Django REST API backend.

## Running with Docker

```bash
# Build and start backend + PostgreSQL
docker compose up --build

# Run in background
docker compose up -d --build
```

- **API**: http://localhost:8001
- **Admin**: http://localhost:8001/admin/

### Useful commands

```bash
# Create superuser
docker compose exec backend uv run python manage.py createsuperuser

# Run migrations manually
docker compose exec backend uv run python manage.py migrate

# View logs
docker compose logs -f backend

# Stop
docker compose down
```

### Optional: use .env for secrets

Copy `.env.example` to `.env` and set `SECRET_KEY`, `POSTGRES_PASSWORD`, etc. Then run:

```bash
docker compose --env-file .env up --build
```

## Local development (without Docker)

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

Uses SQLite by default. For PostgreSQL, set `DB_HOST=localhost` in `.env`.
