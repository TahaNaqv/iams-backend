from datetime import date, timedelta

from django.core.management.base import BaseCommand

from iams.models import AuditableEntity, Audit, Finding, CorrectiveAction


class Command(BaseCommand):
    help = "Seed a small demo dataset for non-production environments"

    def handle(self, *args, **options):
        # Department is an auditable entity now; the audit/finding/CAP rows
        # carry the department as their free-text label (what dashboards read).
        dept, _ = AuditableEntity.all_objects.get_or_create(
            name="Information Technology",
            entity_type="Department",
            defaults={"risk_rating": "High", "status": "Active"},
        )
        dept_name = dept.name

        today = date.today()
        audit, _ = Audit.objects.get_or_create(
            title="IT Security Review",
            defaults={
                "department": dept_name,
                "lead_auditor": "Lead Auditor",
                "status": "In Progress",
                "start_date": today - timedelta(days=10),
                "end_date": today + timedelta(days=20),
                "priority": "High",
                "risk_rating": "High",
                "scope": "Network, IAM, and endpoint controls",
                "objectives": "Validate core security controls",
                "completion_percent": 45,
                "findings_count": 1,
            },
        )

        finding, _ = Finding.objects.get_or_create(
            title="Privileged access reviews not periodic",
            audit=audit,
            defaults={
                "department": dept_name,
                "severity": "High",
                "status": "Open",
                "owner": "Security Manager",
                "due_date": today + timedelta(days=30),
                "description": "Privileged account reviews are not performed quarterly.",
                "root_cause": "No enforced control owner cadence.",
                "recommendation": "Establish quarterly certification workflow.",
                "created_date": today,
            },
        )

        CorrectiveAction.objects.get_or_create(
            title="Implement quarterly privileged access recertification",
            finding=finding,
            defaults={
                "owner": "Security Manager",
                "due_date": today + timedelta(days=45),
                "status": "In Progress",
                "priority": "High",
                "description": "Define and execute recurring access review process.",
                "progress": 25,
                "department": dept_name,
            },
        )

        self.stdout.write(self.style.SUCCESS("Demo dataset seeded successfully."))
