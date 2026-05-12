"""Settings package.

Selection is driven by the DJANGO_SETTINGS_MODULE environment variable.

- config.settings.dev   — local development (DEBUG=True, SQLite fallback, mailhog)
- config.settings.prod  — production (gunicorn, MinIO, real SMTP, Sentry)
- config.settings.test  — test runs (in-memory SQLite, fast hashers, no migrations)

The base module holds settings shared by all environments.
"""
