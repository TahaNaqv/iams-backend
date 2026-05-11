from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from iams.models import Permission, Role, UserProfile

User = get_user_model()


class DomainApiTests(APITestCase):
    def setUp(self):
        self.permissions = {
            key: Permission.objects.create(key=key, name=key, description="", module="test")
            for key in [
                "view_audits",
                "create_audits",
                "edit_audits",
                "delete_audits",
                "manage_findings",
                "manage_caps",
                "view_reports",
                "manage_settings",
            ]
        }
        role = Role.objects.create(name="Audit Manager")
        role.permissions.set(self.permissions.values())
        self.user = User.objects.create_user(username="tester", email="tester@example.com", password="Password123!")
        UserProfile.objects.create(user=self.user, role=role, department="Internal Audit", status="Active")
        token_res = self.client.post("/api/auth/token/", {"username": "tester", "password": "Password123!"}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_res.data['access']}")

    def test_audit_finding_cap_crud_flow(self):
        audit_payload = {
            "title": "Test Audit",
            "department": "Finance",
            "leadAuditor": "Tester",
            "status": "Planned",
            "startDate": "2026-05-01",
            "endDate": "2026-06-01",
            "priority": "High",
            "riskRating": "High",
            "scope": "Scope",
            "objectives": "Objectives",
            "completionPercent": 0,
            "findingsCount": 0,
        }
        audit_res = self.client.post("/api/audits/", audit_payload, format="json")
        self.assertEqual(audit_res.status_code, status.HTTP_201_CREATED)
        audit_id = audit_res.data["id"]

        finding_res = self.client.post(
            "/api/findings/",
            {
                "title": "Test Finding",
                "auditId": audit_id,
                "department": "Finance",
                "severity": "High",
                "status": "Open",
                "owner": "Owner",
                "dueDate": "2026-06-15",
                "description": "Desc",
                "rootCause": "Cause",
                "recommendation": "Fix",
                "createdDate": "2026-05-11",
            },
            format="json",
        )
        self.assertEqual(finding_res.status_code, status.HTTP_201_CREATED)
        finding_id = finding_res.data["id"]

        cap_res = self.client.post(
            "/api/corrective-actions/",
            {
                "title": "CAP",
                "findingId": finding_id,
                "owner": "Owner",
                "dueDate": "2026-06-30",
                "status": "Open",
                "priority": "Medium",
                "description": "Do it",
                "progress": 20,
                "department": "Finance",
            },
            format="json",
        )
        self.assertEqual(cap_res.status_code, status.HTTP_201_CREATED)

        list_res = self.client.get("/api/dashboard/kpis/")
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        self.assertIn("openAudits", list_res.data)

    def test_permission_denied_without_view_audits(self):
        restricted_role = Role.objects.create(name="Restricted")
        user = User.objects.create_user(username="restricted", email="restricted@example.com", password="Password123!")
        UserProfile.objects.create(user=user, role=restricted_role, department="", status="Active")
        token_res = self.client.post("/api/auth/token/", {"username": "restricted", "password": "Password123!"}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_res.data['access']}")
        res = self.client.get("/api/audits/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
