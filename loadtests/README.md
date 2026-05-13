# IAMS Load Tests

Locust-based load test scenario for the IAMS API. Target: **500 concurrent users**, **p95 < 500ms** on top endpoints (NFR-Performance).

## What it exercises

Weighted to mirror the FE's actual polling cadence:

| Endpoint | Weight | Why |
|---|---|---|
| `GET /api/dashboard/kpis/` | 10 | KPI poll, ~60s cadence |
| `GET /api/notifications/unread-count/` | 10 | Topbar bell, ~60s cadence |
| `GET /api/findings/?page=1` | 6 | List view, frequent |
| `GET /api/corrective-actions/?page=1` | 6 | List view, frequent |
| `GET /api/audits/?page=1` | 4 | List view |
| `GET /api/approval-requests/?mine=pending` | 4 | Approvals widget |
| `GET /api/dashboard/role/<role>/` | 3 | Role-specific bundle |
| `GET /api/dashboard/trends/?period=YoY` | 2 | Chart widget |
| `GET /api/dashboard/risk-heatmap/` | 2 | Heat-map widget |
| `GET /api/reports/jobs/` | 2 | Reports tab |
| `GET /api/auth/me/` | 1 | App boot |

## Running

```bash
# Headless, 500 users, 25-user ramp, 5-minute run, HTML report
locust -f loadtests/locustfile.py \
       --host http://staging.iams.internal \
       -u 500 -r 25 --headless \
       --run-time 5m \
       --html loadtests/report.html

# Interactive (web UI on :8089)
locust -f loadtests/locustfile.py --host http://localhost:8001
```

## Environment

```bash
export IAMS_LOAD_USERNAME=loadtest@iams.local
export IAMS_LOAD_PASSWORD=...
```

The test user should hold the **Audit Manager** role so it has read access to every list endpoint exercised. Create it via `manage.py shell` if needed:

```python
from django.contrib.auth import get_user_model
from iams.models import Role, UserProfile
User = get_user_model()
u = User.objects.create_user(
    username="loadtest@iams.local",
    email="loadtest@iams.local",
    password="<strong-password>",
)
UserProfile.objects.create(
    user=u, role=Role.objects.get(name="Audit Manager"),
    department="Internal Audit", status="Active",
)
```

## Interpreting results

- **p95 < 500ms** on the cache-warm dashboard endpoints (kpis / trends / risk-heatmap / ratings).
- **p95 < 750ms** on the list endpoints (findings / caps / audits) at 25 rows per page.
- **error rate < 0.1%** — anything higher is a bug or a missing index.
- **Auth refresh queries** should be a tiny fraction of total traffic (long-lived access tokens).

Persist the HTML report alongside the deploy artifacts — regression comparisons are easier when you have a baseline.
