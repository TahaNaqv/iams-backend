"""Locust load test for IAMS — Phase 5 Track 2.

Target (NFR-Performance):
  - 500 concurrent users
  - p95 < 500 ms on top endpoints
  - Dashboard < 3 s end-to-end
  - File upload (10MB) < 15 s

Usage:

    locust -f loadtests/locustfile.py \\
           --host http://localhost:8001 \\
           -u 500 -r 25 --headless \\
           --run-time 5m \\
           --html loadtests/report.html

Environment:

    IAMS_LOAD_USERNAME=loadtest@iams.local
    IAMS_LOAD_PASSWORD=<change-me>

The script seeds nothing — point it at a staging environment with
realistic data. Each virtual user logs in once, then loops the
weighted task list (heavier weight = more frequent). Tokens are
refreshed when a 401 is observed.
"""
from __future__ import annotations

import os
import random
from typing import Any

from locust import HttpUser, between, events, task


USERNAME = os.getenv("IAMS_LOAD_USERNAME", "loadtest@iams.local")
PASSWORD = os.getenv("IAMS_LOAD_PASSWORD", "loadtest-password")


@events.test_start.add_listener
def _print_target(environment, **kwargs):
    print(f"[locust] hitting {environment.host} as {USERNAME}")


class IAMSUser(HttpUser):
    """One simulated auditor.

    The task weights mirror the FE's actual polling pattern:
      - Dashboard KPI poll every ~60s → weight 10
      - Notifications bell every ~60s → weight 10
      - Findings list page views → weight 6
      - Detail-view drilldowns → weight 4
      - Reports list → weight 2
      - Approvals "mine=pending" → weight 4
    """

    wait_time = between(0.5, 2.0)
    access_token: str | None = None
    refresh_token: str | None = None

    def on_start(self) -> None:
        self._login()

    # ──────────────────────────────────────────────────────────────────
    # Auth
    # ──────────────────────────────────────────────────────────────────
    def _login(self) -> None:
        res = self.client.post(
            "/api/auth/token/",
            json={"username": USERNAME, "password": PASSWORD},
            name="auth/token (POST)",
        )
        if res.status_code != 200:
            return
        data = res.json()
        self.access_token = data.get("access")
        self.refresh_token = data.get("refresh")

    def _headers(self) -> dict[str, str]:
        if not self.access_token:
            return {}
        return {"Authorization": f"Bearer {self.access_token}"}

    def _get(self, path: str, name: str | None = None, **kwargs: Any):
        res = self.client.get(
            path,
            headers=self._headers(),
            name=name or path,
            **kwargs,
        )
        if res.status_code == 401 and self.refresh_token:
            self._refresh()
            res = self.client.get(
                path,
                headers=self._headers(),
                name=name or path,
                **kwargs,
            )
        return res

    def _refresh(self) -> None:
        if not self.refresh_token:
            return
        res = self.client.post(
            "/api/auth/token/refresh/",
            json={"refresh": self.refresh_token},
            name="auth/token/refresh (POST)",
        )
        if res.status_code == 200:
            self.access_token = res.json().get("access")

    # ──────────────────────────────────────────────────────────────────
    # Task weights mirror real polling cadence
    # ──────────────────────────────────────────────────────────────────
    @task(10)
    def dashboard_kpis(self) -> None:
        self._get("/api/dashboard/kpis/", name="dashboard/kpis (GET)")

    @task(10)
    def notifications_bell(self) -> None:
        self._get(
            "/api/notifications/unread-count/",
            name="notifications/unread-count (GET)",
        )

    @task(6)
    def findings_list(self) -> None:
        self._get("/api/findings/?page=1", name="findings (GET list)")

    @task(6)
    def caps_list(self) -> None:
        self._get(
            "/api/corrective-actions/?page=1",
            name="corrective-actions (GET list)",
        )

    @task(4)
    def audits_list(self) -> None:
        self._get("/api/audits/?page=1", name="audits (GET list)")

    @task(4)
    def approvals_mine_pending(self) -> None:
        self._get(
            "/api/approval-requests/?mine=pending",
            name="approval-requests (GET mine=pending)",
        )

    @task(3)
    def dashboard_role(self) -> None:
        role = random.choice(("executive", "manager", "auditor", "auditee"))
        self._get(
            f"/api/dashboard/role/{role}/",
            name="dashboard/role/<role> (GET)",
        )

    @task(2)
    def dashboard_trends(self) -> None:
        self._get(
            "/api/dashboard/trends/?period=YoY",
            name="dashboard/trends (GET YoY)",
        )

    @task(2)
    def dashboard_heatmap(self) -> None:
        self._get(
            "/api/dashboard/risk-heatmap/",
            name="dashboard/risk-heatmap (GET)",
        )

    @task(2)
    def reports_list(self) -> None:
        self._get("/api/reports/jobs/", name="reports/jobs (GET list)")

    @task(1)
    def me(self) -> None:
        self._get("/api/auth/me/", name="auth/me (GET)")
