# IAMS Deployment Checklist

## Pre-deploy
- Confirm environment variables (`SECRET_KEY`, `DEBUG`, DB and JWT settings) are set for target environment.
- Verify object/media storage configuration and credentials.
- Run backend migrations in a staging-like environment and validate rollback plan.
- Build frontend and verify API base URL points to the target backend.

## Deployment
- Deploy backend image/artifacts.
- Run `python manage.py migrate`.
- (Optional non-prod) seed RBAC and demo data:
  - `python manage.py seed_rbac`
  - `python manage.py seed_demo_data`
- Deploy frontend assets.

## Post-deploy verification
- Check health endpoints:
  - `GET /health/` returns `ok`
  - `GET /ready/` returns `ready`
- Validate login/token flow and role-based access controls.
- Validate critical workflows:
  - checklist create/update/delete
  - evidence upload/download
  - timeline creation
  - approvals, work programs, reports, managed documents
- Confirm logs include `X-Request-ID`.

## Backups and operations
- Ensure database backups are enabled and tested.
- Ensure media/object storage backup/retention is configured.
- Enable CI required checks for merge and production promotion.
