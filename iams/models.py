import uuid
from django.conf import settings
from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


class Permission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    module = models.CharField(max_length=100)

    class Meta:
        ordering = ["module", "key"]

    def __str__(self):
        return f"{self.key} ({self.module})"


class Role(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_super_admin = models.BooleanField(default=False)
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    STATUS_CHOICES = [
        ("Active", "Active"),
        ("Inactive", "Inactive"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="user_profiles",
        null=True,
        blank=True,
    )
    department = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Active")

    def __str__(self):
        return f"{self.user.email} - {self.role.name if self.role else 'No role'}"


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Department(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)
    head = models.CharField(max_length=200, blank=True)
    risk_rating = models.CharField(max_length=20, default="Medium")
    last_audit_date = models.DateField(null=True, blank=True)
    next_audit_date = models.DateField(null=True, blank=True)
    entity_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Audit(TimeStampedModel):
    STATUS_CHOICES = [
        ("Planned", "Planned"),
        ("In Progress", "In Progress"),
        ("Review", "Review"),
        ("Completed", "Completed"),
    ]
    PRIORITY_CHOICES = [("High", "High"), ("Medium", "Medium"), ("Low", "Low")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    department = models.CharField(max_length=200)
    department_ref = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="audits"
    )
    lead_auditor = models.CharField(max_length=200)
    lead_auditor_ref = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="led_audits"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Planned")
    start_date = models.DateField()
    end_date = models.DateField()
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="Medium")
    risk_rating = models.CharField(max_length=20, default="Medium")
    scope = models.TextField(blank=True)
    objectives = models.TextField(blank=True)
    completion_percent = models.PositiveIntegerField(default=0)
    findings_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-start_date", "title"]
        indexes = [models.Index(fields=["status", "start_date"])]

    def __str__(self):
        return self.title


class Finding(TimeStampedModel):
    SEVERITY_CHOICES = [("Critical", "Critical"), ("High", "High"), ("Medium", "Medium"), ("Low", "Low")]
    STATUS_CHOICES = [("Open", "Open"), ("In Progress", "In Progress"), ("Resolved", "Resolved"), ("Closed", "Closed")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="findings")
    department = models.CharField(max_length=200)
    department_ref = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="findings"
    )
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default="Medium")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Open")
    owner = models.CharField(max_length=200)
    owner_ref = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="owned_findings"
    )
    due_date = models.DateField()
    description = models.TextField(blank=True)
    root_cause = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)
    created_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-due_date", "title"]
        indexes = [models.Index(fields=["status", "due_date"])]

    def __str__(self):
        return self.title


class CorrectiveAction(TimeStampedModel):
    STATUS_CHOICES = [("Open", "Open"), ("In Progress", "In Progress"), ("Overdue", "Overdue"), ("Closed", "Closed")]
    PRIORITY_CHOICES = [("High", "High"), ("Medium", "Medium"), ("Low", "Low")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    finding = models.ForeignKey(Finding, on_delete=models.CASCADE, related_name="corrective_actions")
    owner = models.CharField(max_length=200)
    owner_ref = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="owned_corrective_actions"
    )
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Open")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="Medium")
    description = models.TextField(blank=True)
    progress = models.PositiveIntegerField(default=0)
    department = models.CharField(max_length=200)
    department_ref = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="corrective_actions"
    )

    class Meta:
        ordering = ["-due_date", "title"]
        indexes = [models.Index(fields=["status", "due_date"])]

    def __str__(self):
        return self.title


class ActivityItem(TimeStampedModel):
    TYPE_CHOICES = [("audit", "audit"), ("finding", "finding"), ("cap", "cap"), ("system", "system")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action = models.CharField(max_length=255)
    user = models.CharField(max_length=200)
    target = models.CharField(max_length=255)
    timestamp = models.DateTimeField()
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="system")

    class Meta:
        ordering = ["-timestamp"]


class ChecklistItem(TimeStampedModel):
    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("In Progress", "In Progress"),
        ("Complete", "Complete"),
        ("N/A", "N/A"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="checklist_items")
    title = models.CharField(max_length=255)
    assignee = models.CharField(max_length=200, blank=True)
    assignee_ref = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_checklist_items"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending")
    notes = models.TextField(blank=True)


class EvidenceFile(TimeStampedModel):
    """An audit working-paper attachment.

    Files are stored on local disk (dev) or MinIO/S3 (prod) — selected via
    the ``USE_S3_STORAGE`` / ``STORAGES`` settings, not anything model-level.

    Every upload is virus-scanned asynchronously by
    ``iams.tasks.scans.scan_evidence_file`` (Celery + clamd). The scan
    result lives on the row itself:

      - ``SCAN_PENDING``  — task not yet completed
      - ``SCAN_CLEAN``    — clamd returned OK
      - ``SCAN_INFECTED`` — clamd flagged the file; ``quarantined=True`` and
                            downloads are blocked
      - ``SCAN_ERROR``    — clamd unreachable / non-fatal scan failure;
                            human review required
    """

    SCAN_PENDING = "pending"
    SCAN_CLEAN = "clean"
    SCAN_INFECTED = "infected"
    SCAN_ERROR = "error"
    SCAN_STATUS_CHOICES = [
        (SCAN_PENDING, "Pending"),
        (SCAN_CLEAN, "Clean"),
        (SCAN_INFECTED, "Infected"),
        (SCAN_ERROR, "Scan error"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="evidence_files")
    file = models.FileField(upload_to="evidence/%Y/%m/%d/", blank=True, null=True)
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=100, blank=True)
    size_kb = models.PositiveIntegerField(default=0)
    uploaded_by = models.CharField(max_length=200, blank=True)
    uploaded_by_ref = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="uploaded_evidence_files"
    )
    uploaded_at = models.DateTimeField()

    # AV scan state — set asynchronously by iams.tasks.scans
    scan_status = models.CharField(
        max_length=20, choices=SCAN_STATUS_CHOICES, default=SCAN_PENDING, db_index=True
    )
    scan_signature = models.CharField(max_length=255, blank=True)  # virus name from clamd
    scanned_at = models.DateTimeField(null=True, blank=True)
    quarantined = models.BooleanField(default=False, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["audit", "uploaded_at"])]


class TimelineEvent(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="timeline_events")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    timestamp = models.DateTimeField()

    class Meta:
        ordering = ["-timestamp"]


class AuditableEntity(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    department = models.CharField(max_length=200)
    department_ref = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="auditable_entities"
    )
    owner = models.CharField(max_length=200, blank=True)
    risk_rating = models.CharField(max_length=20, default="Medium")
    last_audit_date = models.DateField(null=True, blank=True)
    next_audit_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=50, default="Active")


class RiskHistoryEntry(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.CharField(max_length=255)
    entity_ref = models.ForeignKey(
        AuditableEntity, on_delete=models.SET_NULL, null=True, blank=True, related_name="risk_history_entries"
    )
    date = models.DateField()
    previous_rating = models.CharField(max_length=20)
    current_rating = models.CharField(max_length=20)
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-date"]


class Notification(TimeStampedModel):
    """A delivered notification.

    Notifications are produced by ``iams.notifications.dispatch(...)``, which
    fans out a single event into an in-app row here (if the recipient's
    preferences allow) and an email (likewise).

    A ``recipient`` of ``None`` indicates a **system-wide broadcast** —
    shown to every authenticated user. Backwards-compatible with the
    pre-Phase-2 schema where every notification was implicitly global.
    """

    # Notification taxonomy — keep stable; the FE filters and the
    # NotificationPreference matrix join on these values.
    KIND_AUDIT_ASSIGNED = "audit_assigned"
    KIND_AUDIT_STATUS_CHANGE = "audit_status_change"
    KIND_FINDING_RAISED = "finding_raised"
    KIND_CAP_ASSIGNED = "cap_assigned"
    KIND_CAP_DUE_SOON = "cap_due_soon"
    KIND_CAP_OVERDUE = "cap_overdue"
    KIND_APPROVAL_REQUESTED = "approval_requested"
    KIND_APPROVAL_APPROVED = "approval_approved"
    KIND_APPROVAL_REJECTED = "approval_rejected"
    KIND_PASSWORD_RESET = "password_reset"
    KIND_FILE_QUARANTINE = "file_quarantine"
    KIND_WEEKLY_DIGEST = "weekly_digest"
    KIND_MFA_REMINDER = "mfa_reminder"
    KIND_GENERIC = "generic"

    KIND_CHOICES = [
        (KIND_AUDIT_ASSIGNED, "Audit assigned"),
        (KIND_AUDIT_STATUS_CHANGE, "Audit status changed"),
        (KIND_FINDING_RAISED, "Finding raised"),
        (KIND_CAP_ASSIGNED, "CAP assigned"),
        (KIND_CAP_DUE_SOON, "CAP due in 3 days"),
        (KIND_CAP_OVERDUE, "CAP overdue"),
        (KIND_APPROVAL_REQUESTED, "Approval requested"),
        (KIND_APPROVAL_APPROVED, "Approval approved"),
        (KIND_APPROVAL_REJECTED, "Approval rejected"),
        (KIND_PASSWORD_RESET, "Password reset"),
        (KIND_FILE_QUARANTINE, "File quarantined"),
        (KIND_WEEKLY_DIGEST, "Weekly digest"),
        (KIND_MFA_REMINDER, "MFA setup reminder"),
        (KIND_GENERIC, "Generic"),
    ]

    # Cosmetic urgency: drives the FE icon/colour.
    LEVEL_INFO = "info"
    LEVEL_WARNING = "warning"
    LEVEL_ACTION = "action"
    LEVEL_CHOICES = [
        (LEVEL_INFO, "Info"),
        (LEVEL_WARNING, "Warning"),
        (LEVEL_ACTION, "Action required"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True, blank=True,
        help_text="Specific recipient. NULL = system-wide broadcast.",
    )
    kind = models.CharField(
        max_length=40, choices=KIND_CHOICES, default=KIND_GENERIC, db_index=True
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    type = models.CharField(max_length=20, choices=LEVEL_CHOICES, default=LEVEL_INFO)

    # Optional pointer back at the affected object.
    target_content_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    target_object_id = models.UUIDField(null=True, blank=True)
    target_object = GenericForeignKey("target_content_type", "target_object_id")

    # FE deep-link (e.g. "/findings/F-001"). Lets the topbar bell jump
    # straight to the object without consulting a routing table.
    link = models.CharField(max_length=512, blank=True)

    # Free-form module label (e.g. "CAPs", "Audits"). Used by the FE for
    # filtering + grouping.
    module = models.CharField(max_length=64, blank=True)

    read = models.BooleanField(default=False, db_index=True)
    timestamp = models.DateTimeField(db_index=True)

    # Email delivery state, written by the notify task.
    email_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["recipient", "read", "-timestamp"]),
            models.Index(fields=["kind", "-timestamp"]),
        ]


class NotificationPreference(TimeStampedModel):
    """Per-user, per-kind delivery preferences.

    A user with no row for a given ``kind`` falls back to ``DEFAULT_PREFS``
    (defined in ``iams.notifications``). New kinds are therefore opt-out by
    default for all existing users without requiring a data backfill.

    The matrix is intentionally simple: in_app + email. SMS and push are
    on the Phase 6 roadmap.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    kind = models.CharField(max_length=40, choices=Notification.KIND_CHOICES)
    in_app_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "kind"],
                name="iams_notif_pref_user_kind_unique",
            ),
        ]
        ordering = ["user_id", "kind"]


class AuditLogEntry(TimeStampedModel):
    """Append-only audit trail.

    Every meaningful state change in the system writes a row here via
    ``iams.audit.AuditedViewSetMixin`` (auto-capture on every DRF ViewSet)
    or explicit ``record_audit_event(...)`` calls from signal handlers /
    Celery tasks. Once written, rows are **never updated or deleted** —
    ``save()`` rejects updates and ``delete()`` raises. The DB-level
    enforcement (Postgres REVOKE UPDATE/DELETE) is added in Phase 5 hardening.

    Required for IIA 2330 documentation traceability and the 7-year
    retention policy (FR-LOG-05).
    """

    # Action verbs. The FE filters on these so keep the set small/stable.
    ACTION_CREATE = "create"
    ACTION_UPDATE = "update"
    ACTION_DELETE = "delete"
    ACTION_APPROVE = "approve"
    ACTION_REJECT = "reject"
    ACTION_LOGIN = "login"
    ACTION_LOGOUT = "logout"
    ACTION_PASSWORD_RESET = "password_reset"
    ACTION_PASSWORD_CHANGE = "password_change"
    ACTION_FILE_UPLOAD = "file_upload"
    ACTION_FILE_QUARANTINE = "file_quarantine"
    ACTION_EXPORT = "export"
    ACTION_OTHER = "other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.CharField(max_length=200, help_text="Email or display name at the time of the action.")
    actor_ref = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="audit_log_entries",
    )
    action = models.CharField(max_length=64, db_index=True)
    target = models.CharField(max_length=255, help_text="Human label of the affected object.")
    target_content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    target_object_id = models.UUIDField(null=True, blank=True)
    target_object = GenericForeignKey("target_content_type", "target_object_id")
    timestamp = models.DateTimeField(db_index=True)

    # Auto-capture metadata
    request_id = models.CharField(max_length=64, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)

    # Diff payload: ``{field: {"old": ..., "new": ...}}`` on update;
    # full snapshot on create/delete (under the "snapshot" key).
    changes = models.JSONField(default=dict, blank=True)

    # Free-form context (CAP closure reason, approval comments, etc.).
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["-timestamp"]),
            models.Index(fields=["actor_ref", "-timestamp"]),
            models.Index(fields=["target_content_type", "target_object_id"]),
            models.Index(fields=["action", "-timestamp"]),
        ]

    def save(self, *args, **kwargs):
        # Append-only enforcement: ``_state.adding`` is True only when
        # Django is about to INSERT. Instances loaded from the DB (or
        # re-saved after their first save) flip it to False, and we reject.
        if not self._state.adding:
            raise PermissionError(
                "AuditLogEntry is append-only; updates are forbidden. "
                "Create a new row instead.",
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # noqa: D401 — enforces immutability
        raise PermissionError(
            "AuditLogEntry is append-only; deletes are forbidden. Run the "
            "scheduled retention task as a privileged admin to expire rows.",
        )


class FollowUpItem(TimeStampedModel):
    STATUS_CHOICES = [("Pending", "Pending"), ("In Progress", "In Progress"), ("Completed", "Completed")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    finding = models.ForeignKey(Finding, on_delete=models.CASCADE, related_name="follow_ups")
    owner = models.CharField(max_length=200)
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending")
    notes = models.TextField(blank=True)


class Comment(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity_id = models.CharField(max_length=100, db_index=True)
    target_content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    target_object_id = models.UUIDField(null=True, blank=True)
    target_object = GenericForeignKey("target_content_type", "target_object_id")
    author = models.CharField(max_length=200)
    author_ref = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="comments_authored"
    )
    text = models.TextField()
    created_at = models.DateTimeField()

    class Meta:
        ordering = ["created_at"]


class Auditor(TimeStampedModel):
    AVAILABILITY_CHOICES = [("Available", "Available"), ("On Audit", "On Audit"), ("On Leave", "On Leave")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    role = models.CharField(max_length=100, blank=True)
    availability = models.CharField(max_length=20, choices=AVAILABILITY_CHOICES, default="Available")
    skills = models.JSONField(default=list, blank=True)
    certifications = models.JSONField(default=list, blank=True)
    weekly_capacity_hours = models.PositiveIntegerField(default=40)

    class Meta:
        ordering = ["name"]


class AuditAssignment(TimeStampedModel):
    PHASE_CHOICES = [("Planning", "Planning"), ("Fieldwork", "Fieldwork"), ("Reporting", "Reporting"), ("Review", "Review")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    auditor = models.ForeignKey(Auditor, on_delete=models.CASCADE, related_name="assignments")
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="assignments")
    phase = models.CharField(max_length=20, choices=PHASE_CHOICES, default="Planning")
    allocation_pct = models.PositiveIntegerField(default=100)
    start_date = models.DateField()
    end_date = models.DateField()


class TimeEntry(TimeStampedModel):
    STATUS_CHOICES = [("Draft", "Draft"), ("Submitted", "Submitted"), ("Approved", "Approved")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    auditor = models.ForeignKey(Auditor, on_delete=models.CASCADE, related_name="time_entries")
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="time_entries")
    date = models.DateField()
    hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Draft")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-date"]


class HoursBudget(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit = models.OneToOneField(Audit, on_delete=models.CASCADE, related_name="hours_budget")
    budgeted_hours = models.PositiveIntegerField(default=0)
    consumed_hours = models.PositiveIntegerField(default=0)


class RiskAssessmentSheet(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]


class RiskAssessmentRecord(TimeStampedModel):
    LEVEL_CHOICES = [("High", "High"), ("Medium", "Medium"), ("Low", "Low")]
    INCLUSION_CHOICES = [("Included", "Included"), ("Excluded", "Excluded"), ("Deferred", "Deferred")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sheet = models.ForeignKey(RiskAssessmentSheet, on_delete=models.SET_NULL, null=True, blank=True, related_name="records")
    source_sheet = models.CharField(max_length=255, blank=True)
    source_row = models.PositiveIntegerField(default=0)
    department = models.CharField(max_length=200)
    objective = models.TextField(blank=True)
    risk_area = models.CharField(max_length=255)
    risk_description = models.TextField(blank=True)
    grading = models.CharField(max_length=50, blank=True)
    likelihood = models.CharField(max_length=20, default="Medium")
    impact = models.CharField(max_length=20, default="Medium")
    inherent_risk = models.CharField(max_length=20, choices=LEVEL_CHOICES, default="Medium")
    existing_controls = models.TextField(blank=True)
    control_effectiveness = models.CharField(max_length=50, blank=True)
    residual_risk = models.CharField(max_length=20, choices=LEVEL_CHOICES, default="Medium")
    audit_objective = models.TextField(blank=True)
    audit_steps = models.TextField(blank=True)
    documents_required = models.TextField(blank=True)
    inclusion_status = models.CharField(max_length=20, choices=INCLUSION_CHOICES, default="Included")
    audit_scope = models.TextField(blank=True)
    planned_man_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    notes = models.TextField(blank=True)


class RiskAssessmentMatrixCell(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    likelihood = models.CharField(max_length=50)
    impact = models.CharField(max_length=50)
    residual_risk = models.CharField(max_length=20, default="Medium")

    class Meta:
        unique_together = ("likelihood", "impact")


class RiskAssessmentSummaryItem(TimeStampedModel):
    INCLUSION_CHOICES = [("Included", "Included"), ("Excluded", "Excluded"), ("Deferred", "Deferred")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    record = models.ForeignKey(RiskAssessmentRecord, on_delete=models.CASCADE, related_name="summary_items")
    inclusion_status = models.CharField(max_length=20, choices=INCLUSION_CHOICES, default="Included")
    audit_scope = models.TextField(blank=True)
    planned_man_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)


class RiskAssessmentImportIssue(TimeStampedModel):
    SEVERITY_CHOICES = [("error", "error"), ("warning", "warning"), ("info", "info")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default="warning")
    # Matches the FE contract `{ sheet, cell }`. ``cell`` is a free-form
    # Excel-style reference (e.g. "B14") so renderers can deep-link straight to
    # the offending workbook cell. ``row_number`` is kept for backwards
    # compatibility and ordering.
    sheet = models.CharField(max_length=255, blank=True)
    cell = models.CharField(max_length=20, blank=True)
    row_number = models.PositiveIntegerField(default=0)
    message = models.TextField()


class ApprovalRequest(TimeStampedModel):
    STATUS_CHOICES = [("Pending", "Pending"), ("Approved", "Approved"), ("Rejected", "Rejected"), ("Returned", "Returned")]
    TYPE_CHOICES = [("Audit Plan", "Audit Plan"), ("Finding", "Finding"), ("CAP Closure", "CAP Closure"), ("Report", "Report"), ("Risk Assessment", "Risk Assessment")]
    PRIORITY_CHOICES = [("High", "High"), ("Medium", "Medium"), ("Low", "Low")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    type = models.CharField(max_length=50, choices=TYPE_CHOICES, db_index=True)
    reference_id = models.CharField(max_length=100, blank=True, db_index=True)
    department = models.CharField(max_length=200, blank=True)
    submitted_by = models.CharField(max_length=200, blank=True)
    submitted_date = models.DateField(null=True, blank=True)
    current_step = models.PositiveIntegerField(default=0)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="Medium")
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending", db_index=True)

    # When the request was last actioned (used by escalation telemetry +
    # FE staleness badges). Set automatically by approve/reject.
    last_action_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class ApprovalStep(TimeStampedModel):
    STATUS_CHOICES = ApprovalRequest.STATUS_CHOICES

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(ApprovalRequest, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveIntegerField(default=0)
    role = models.CharField(max_length=100, blank=True, db_index=True)
    approver = models.CharField(max_length=200, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending", db_index=True)
    date = models.DateField(null=True, blank=True)
    comments = models.TextField(blank=True)

    # SLA fields driven by the chain template that applied this step.
    sla_days = models.PositiveIntegerField(
        default=7,
        help_text="How long this step has before it's eligible for escalation.",
    )
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    escalated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order", "created_at"]


class ApprovalChainTemplate(TimeStampedModel):
    """Configurable approval chain for a given request type.

    Tooling rule: when an ``ApprovalRequest`` is created with no
    explicit ``steps``, the matching active template's ``chain`` is
    expanded into ``ApprovalStep`` rows automatically.

    ``chain`` is a JSON array of step descriptors::

        [
          {"role": "Audit Manager",  "sla_days": 3},
          {"role": "CAE",            "sla_days": 5},
          {"role": "Board",          "sla_days": 14}
        ]

    The optional ``approver_role_attr`` (default ``role``) lets a template
    target a Permission key or other role attribute when the chain needs
    to dispatch to a specific user rather than fan-out by role name.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)
    request_type = models.CharField(max_length=50, choices=ApprovalRequest.TYPE_CHOICES)
    chain = models.JSONField(
        default=list,
        help_text="Ordered list of {role, sla_days} step descriptors.",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["request_type", "name"]
        constraints = [
            # At most one active template per request type — keeps auto-apply
            # deterministic. Admin must deactivate the old one before
            # activating a replacement.
            models.UniqueConstraint(
                fields=["request_type"],
                condition=models.Q(is_active=True),
                name="iams_one_active_chain_per_type",
            ),
        ]

    def step_descriptors(self) -> list[dict]:
        """Return the chain as a list of dicts; tolerant of legacy shapes."""
        out: list[dict] = []
        for entry in self.chain or []:
            if isinstance(entry, str):
                out.append({"role": entry, "sla_days": 7})
            elif isinstance(entry, dict):
                out.append({
                    "role": entry.get("role", ""),
                    "sla_days": int(entry.get("sla_days", 7) or 7),
                })
        return out


class WorkProgram(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="work_programs")
    title = models.CharField(max_length=255)

    class Meta:
        ordering = ["-created_at"]


class WorkProcedure(TimeStampedModel):
    STATUS_CHOICES = [("Not Started", "Not Started"), ("In Progress", "In Progress"), ("Completed", "Completed"), ("Reviewed", "Reviewed")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_program = models.ForeignKey(WorkProgram, on_delete=models.CASCADE, related_name="procedures")
    title = models.CharField(max_length=255)
    objective = models.TextField(blank=True)
    risk_area = models.CharField(max_length=255, blank=True)
    control_ref = models.CharField(max_length=100, blank=True)
    assigned_to = models.CharField(max_length=200, blank=True)
    assigned_to_ref = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_work_procedures"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Not Started")
    conclusion = models.TextField(blank=True)
    signed_off_by = models.CharField(max_length=200, blank=True)
    signed_off_by_ref = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="signed_off_work_procedures"
    )
    signed_off_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["title"]


class WorkProcedureStep(TimeStampedModel):
    METHOD_CHOICES = [("Inquiry", "Inquiry"), ("Observation", "Observation"), ("Inspection", "Inspection"), ("Re-performance", "Re-performance"), ("Analytical", "Analytical")]
    RESULT_CHOICES = [("Not Started", "Not Started"), ("Pass", "Pass"), ("Fail", "Fail"), ("N/A", "N/A"), ("Exception", "Exception")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    procedure = models.ForeignKey(WorkProcedure, on_delete=models.CASCADE, related_name="steps")
    description = models.TextField()
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default="Inspection")
    sample_size = models.CharField(max_length=255, blank=True)
    result = models.CharField(max_length=20, choices=RESULT_CHOICES, default="Not Started")
    notes = models.TextField(blank=True)
    completed_by = models.CharField(max_length=200, blank=True)
    completed_by_ref = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="completed_work_steps"
    )
    completed_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]


class AuditReport(TimeStampedModel):
    STATUS_CHOICES = [("Draft", "Draft"), ("In Review", "In Review"), ("Final", "Final")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="reports")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Draft")
    author = models.CharField(max_length=200, blank=True)
    author_ref = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="authored_reports"
    )
    reviewer = models.CharField(max_length=200, blank=True)
    reviewer_ref = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="review_reports"
    )
    created_date = models.DateField(null=True, blank=True)
    last_modified = models.DateField(null=True, blank=True)
    department = models.CharField(max_length=200, blank=True)
    department_ref = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_reports"
    )

    class Meta:
        ordering = ["-last_modified", "-created_at"]


class AuditReportSection(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(AuditReport, on_delete=models.CASCADE, related_name="sections")
    order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=255)
    type = models.CharField(max_length=50)
    content = models.TextField(blank=True)

    class Meta:
        ordering = ["order", "created_at"]


class WorkingPaper(TimeStampedModel):
    """An audit working paper — engagement-scoped evidence with formal sign-off.

    Distinct from ``ManagedDocument`` (which models org-wide policies /
    procedures / templates) because IIA 2330 imposes stricter rules on
    engagement working papers:

      - Each row is bound to a specific ``Audit``.
      - Multi-step sign-off (Auditor → Reviewer). Both timestamps are
        captured separately; ``signed_off_at`` is derived from the
        reviewer step.
      - Once fully signed, the row is **lock-on-finalize**: Python-level
        ``save()`` and ``delete()`` reject modification. FR-WP-06.
      - Versions form a chain via the ``parent`` self-FK. Creating a new
        version flips ``is_current_version`` on the prior row.
      - Cross-references to ``Finding`` via M2M for IIA 2330 traceability.
      - Inherits the scan/quarantine workflow from ``EvidenceFile``.
    """

    STATUS_DRAFT = "Draft"
    STATUS_UNDER_REVIEW = "Under Review"
    STATUS_SIGNED = "Signed"
    STATUS_ARCHIVED = "Archived"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_UNDER_REVIEW, "Under Review"),
        (STATUS_SIGNED, "Signed"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="working_papers")
    reference = models.CharField(
        max_length=50, blank=True, db_index=True,
        help_text="Human reference, e.g. 'WP-001'. Optional; system-generated if blank.",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    file = models.FileField(upload_to="working-papers/%Y/%m/%d/", blank=True, null=True)
    file_type = models.CharField(max_length=20, blank=True)
    file_size_kb = models.PositiveIntegerField(default=0)

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True
    )

    # Version chain. ``parent`` points at the predecessor row (NULL for v1).
    # ``version`` auto-assigns starting at 1. ``is_current_version`` is True
    # for exactly one row in the chain at any time.
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="successors"
    )
    version = models.PositiveIntegerField(default=1)
    is_current_version = models.BooleanField(default=True, db_index=True)

    # Sign-off (FR-WP-03). Both signatures must be present for the row to
    # be considered "finalized".
    auditor_signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="auditor_signed_working_papers",
    )
    auditor_signed_at = models.DateTimeField(null=True, blank=True)
    reviewer_signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="reviewer_signed_working_papers",
    )
    reviewer_signed_at = models.DateTimeField(null=True, blank=True)
    signed_off_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # Cross-references to findings (FR-WP-04). Reverse accessor on
    # Finding is ``working_papers``.
    findings = models.ManyToManyField(
        "Finding", blank=True, related_name="working_papers",
    )

    # AV scan state — mirrors EvidenceFile.
    scan_status = models.CharField(
        max_length=20,
        choices=EvidenceFile.SCAN_STATUS_CHOICES,
        default=EvidenceFile.SCAN_PENDING,
        db_index=True,
    )
    scan_signature = models.CharField(max_length=255, blank=True)
    scanned_at = models.DateTimeField(null=True, blank=True)
    quarantined = models.BooleanField(default=False, db_index=True)

    # Full-text search content. Plain TextField (rather than Postgres
    # tsvector) so the same code path works on SQLite (tests) and on
    # Postgres (prod). The ``extract_text`` Celery task populates this
    # from the file content post-upload.
    searchable_text = models.TextField(blank=True)

    class Meta:
        ordering = ["audit_id", "reference", "-version"]
        indexes = [
            models.Index(fields=["audit", "is_current_version"]),
            models.Index(fields=["audit", "status"]),
            models.Index(fields=["reference"]),
        ]
        constraints = [
            # Enforce a single "current" row per (audit, reference) chain.
            models.UniqueConstraint(
                fields=["audit", "reference"],
                condition=models.Q(is_current_version=True),
                name="iams_wp_one_current_per_audit_ref",
            ),
        ]

    # ── Helpers ─────────────────────────────────────────────────────
    def is_finalized(self) -> bool:
        return bool(self.auditor_signed_at and self.reviewer_signed_at)

    def __str__(self) -> str:
        ref = self.reference or str(self.pk)[:8]
        return f"{ref} v{self.version} — {self.title}"

    # ── Lock-on-finalize (Python-level) ────────────────────────────
    def save(self, *args, **kwargs):
        """Reject updates to a row that's already signed off (FR-WP-06).

        Two carve-outs:
          - The post-upload AV scan worker updates ``scan_*`` fields,
            which may happen after sign-off finishes; allow it.
          - Tests / admin tools that legitimately need to mutate a
            signed row may set ``instance._force_save_signed = True``.
        """
        if (
            not self._state.adding
            and self.signed_off_at is not None
            and not getattr(self, "_force_save_signed", False)
        ):
            allowed_fields = {"scan_status", "scan_signature", "scanned_at", "quarantined"}
            update_fields = kwargs.get("update_fields") or set()
            if update_fields and set(update_fields).issubset(allowed_fields):
                return super().save(*args, **kwargs)
            raise PermissionError(
                "WorkingPaper is locked: signed off on "
                f"{self.signed_off_at.isoformat() if self.signed_off_at else 'unknown'}. "
                "Create a new version instead."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.signed_off_at is not None:
            raise PermissionError(
                "WorkingPaper is locked after sign-off; cannot delete. "
                "Archive instead."
            )
        return super().delete(*args, **kwargs)


class ManagedDocument(TimeStampedModel):
    STATUS_CHOICES = [("Published", "Published"), ("Draft", "Draft"), ("Under Review", "Under Review"), ("Archived", "Archived")]
    CATEGORY_CHOICES = [("Policies", "Policies"), ("Procedures", "Procedures"), ("Standards", "Standards"), ("Templates", "Templates"), ("Evidence", "Evidence"), ("Reports", "Reports")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default="Policies")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Draft")
    owner = models.CharField(max_length=200, blank=True)
    owner_ref = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="owned_documents"
    )
    department = models.CharField(max_length=200, blank=True)
    department_ref = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="managed_documents"
    )
    file = models.FileField(upload_to="documents/%Y/%m/%d/", blank=True, null=True)
    file_type = models.CharField(max_length=20, blank=True)
    file_size = models.CharField(max_length=50, blank=True)
    created_date = models.DateField(null=True, blank=True)
    modified_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    versions = models.JSONField(default=list, blank=True)

    # Mirrors EvidenceFile scan state — same task scans both.
    scan_status = models.CharField(
        max_length=20,
        choices=EvidenceFile.SCAN_STATUS_CHOICES,
        default=EvidenceFile.SCAN_PENDING,
        db_index=True,
    )
    scan_signature = models.CharField(max_length=255, blank=True)
    scanned_at = models.DateTimeField(null=True, blank=True)
    quarantined = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-modified_date", "-created_at"]
