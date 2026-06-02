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
    # Phase 5 — per-role MFA enforcement. When True, users with this role
    # MUST have a confirmed MFADevice before they can complete login.
    mfa_required = models.BooleanField(
        default=False,
        help_text="Force MFA enrollment for every user with this role.",
    )
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
    # Phase 5 — set whenever the password is changed; the MFA grace
    # period (30 days from account creation OR last password change)
    # uses this to decide whether to enforce MFA setup.
    password_changed_at = models.DateTimeField(null=True, blank=True)
    # Phase 5 — last successful login + last activity. Driven by the
    # login flow and the SessionTouchMiddleware. Used by the session
    # timeout policy and the admin "stale account" report.
    last_login_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    # Phase 6 Track 3 — user-selected UI language. RTL is implicit from
    # the locale ("ar" is RTL); the FE flips the document direction.
    LANGUAGE_CHOICES = [
        ("en", "English"),
        ("ar", "العربية"),
        ("fr", "Français"),
    ]
    language = models.CharField(
        max_length=8, choices=LANGUAGE_CHOICES, default="en",
        help_text="Preferred UI language; restored on next login.",
    )

    def __str__(self):
        return f"{self.user.email} - {self.role.name if self.role else 'No role'}"


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ═════════════════════════════════════════════════════════════════════
# Audit Universe — shared enums (Phase 7 Track 1)
#
# Module-level TextChoices for values shared between AuditableEntity,
# Department, BusinessUnit, and the revision history. Locking these
# down at the model level replaces the previous free-text CharField
# pattern that allowed values like "Extreme" to slip in.
# ═════════════════════════════════════════════════════════════════════


class RiskRatingChoices(models.TextChoices):
    LOW = "Low", "Low"
    MEDIUM = "Medium", "Medium"
    HIGH = "High", "High"
    CRITICAL = "Critical", "Critical"


class EntityStatusChoices(models.TextChoices):
    ACTIVE = "Active", "Active"
    INACTIVE = "Inactive", "Inactive"
    ARCHIVED = "Archived", "Archived"


class EntityTypeChoices(models.TextChoices):
    PROCESS = "Process", "Process"
    SYSTEM = "System", "System"
    FUNCTION = "Function", "Function"
    PROJECT = "Project", "Project"
    COMPLIANCE_AREA = "ComplianceArea", "Compliance Area"


class AuditFrequencyChoices(models.TextChoices):
    ANNUAL = "Annual", "Annual"
    SEMI_ANNUAL = "SemiAnnual", "Semi-annual"
    QUARTERLY = "Quarterly", "Quarterly"
    AD_HOC = "AdHoc", "Ad hoc"
    CONTINUOUS = "Continuous", "Continuous"


class LastAuditRatingChoices(models.TextChoices):
    SATISFACTORY = "Satisfactory", "Satisfactory"
    NEEDS_IMPROVEMENT = "NeedsImprovement", "Needs improvement"
    UNSATISFACTORY = "Unsatisfactory", "Unsatisfactory"
    NOT_APPLICABLE = "NA", "Not applicable"


class ComplianceStatusChoices(models.TextChoices):
    COMPLIANT = "Compliant", "Compliant"
    NON_COMPLIANT = "NonCompliant", "Non-compliant"
    IN_REVIEW = "InReview", "In review"
    NOT_ASSESSED = "NotAssessed", "Not assessed"


class TagCategoryChoices(models.TextChoices):
    COMPLIANCE = "Compliance", "Compliance"
    REGULATORY = "Regulatory", "Regulatory"
    FUNCTIONAL = "Functional", "Functional"
    RISK = "Risk", "Risk"
    CUSTOM = "Custom", "Custom"


class AuditableEntityActiveManager(models.Manager):
    """Default manager that excludes Archived rows.

    Use ``AuditableEntity.objects`` for the active set, and
    ``AuditableEntity.all_objects`` when archived rows are required
    (admin views, restore flow, ERP reconciliation).
    """

    def get_queryset(self):  # noqa: D401 - Django manager API
        return super().get_queryset().exclude(status=EntityStatusChoices.ARCHIVED)


class Department(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)
    head = models.CharField(max_length=200, blank=True)
    risk_rating = models.CharField(
        max_length=20,
        choices=RiskRatingChoices.choices,
        default=RiskRatingChoices.MEDIUM,
    )
    last_audit_date = models.DateField(null=True, blank=True)
    next_audit_date = models.DateField(null=True, blank=True)
    entity_count = models.PositiveIntegerField(default=0)
    # Phase 7 Track 1 — link Departments under a BusinessUnit umbrella.
    # Nullable for backfill compatibility; populated by the migration's
    # seed step or by manual mapping in admin.
    business_unit = models.ForeignKey(
        "BusinessUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="departments",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class BusinessUnit(TimeStampedModel):
    """A top-level organizational grouping above Departments.

    The reference design groups Departments under Business Units
    (e.g. "Finance & Treasury" → Accounts Payable, General Ledger).
    Self-referential ``parent`` supports multi-level BU hierarchies
    (Group → Region → BU) without forcing a fixed depth.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=32, blank=True, db_index=True)
    head = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_business_units",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    risk_appetite = models.CharField(
        max_length=20,
        choices=RiskRatingChoices.choices,
        default=RiskRatingChoices.MEDIUM,
    )
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Tag(TimeStampedModel):
    """Reusable classification labels for AuditableEntity and related rows.

    Tags themselves are first-class records (for autocomplete, governance,
    colour assignment). The link to ``AuditableEntity`` stays a JSONField
    of string names — matching the existing convention on ``ManagedDocument``
    — so wire payloads stay simple.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    color = models.CharField(max_length=16, blank=True)
    category = models.CharField(
        max_length=20,
        choices=TagCategoryChoices.choices,
        default=TagCategoryChoices.CUSTOM,
    )
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["category", "name"]

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

    # Phase 6 Track 2 — external system provenance.
    external_source = models.CharField(max_length=64, blank=True, db_index=True)
    external_id = models.CharField(max_length=128, blank=True, db_index=True)

    class Meta:
        ordering = ["-start_date", "title"]
        indexes = [
            models.Index(fields=["status", "start_date"]),
            # Phase 5 Track 2 — dashboards.upcoming_audits filters
            # ``start_date >= today`` + optional department.
            models.Index(fields=["department", "status"]),
            models.Index(fields=["start_date"]),
            models.Index(fields=["lead_auditor"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["external_source", "external_id"],
                condition=~models.Q(external_id=""),
                name="iams_audit_external_unique",
            ),
        ]

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
    # Phase 6 Track 2 — external provenance for inbound ERP findings.
    external_source = models.CharField(max_length=64, blank=True, db_index=True)
    external_id = models.CharField(max_length=128, blank=True, db_index=True)

    class Meta:
        ordering = ["-due_date", "title"]
        indexes = [
            models.Index(fields=["status", "due_date"]),
            # Phase 5 Track 2 — dashboards filter by (department, status)
            # and the auditor role bundle hits (owner, status, due_date).
            models.Index(fields=["department", "status"]),
            models.Index(fields=["owner", "status", "due_date"]),
            models.Index(fields=["severity", "status"]),
            models.Index(fields=["created_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["external_source", "external_id"],
                condition=~models.Q(external_id=""),
                name="iams_finding_external_unique",
            ),
        ]

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
        indexes = [
            models.Index(fields=["status", "due_date"]),
            # Phase 5 Track 2 — CAP-overdue scan + auditee role bundle.
            models.Index(fields=["department", "status"]),
            models.Index(fields=["owner", "status", "due_date"]),
            models.Index(fields=["finding", "status"]),
        ]

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
    # ── DEPRECATED legacy free-text columns ──────────────────────────
    # ``department`` and ``owner`` are retained for backward compatibility
    # with pre-Phase-7 API consumers (the AuditableEntityListSerializer
    # still emits both on the wire, and the contract test asserts their
    # presence). New writes must populate ``department_ref`` /
    # ``primary_owner`` — these scalar columns will be removed in a
    # future migration once telemetry shows zero callers depend on them.
    #
    # Deprecation: 2026-05-15. Removal target: next major release.
    department = models.CharField(
        max_length=200,
        blank=True,
        help_text="DEPRECATED — use ``department_ref`` (FK). Removed in next major release.",
    )
    department_ref = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="auditable_entities"
    )
    owner = models.CharField(
        max_length=200,
        blank=True,
        help_text="DEPRECATED — use ``primary_owner`` (FK to User). Removed in next major release.",
    )

    # ── Phase 7 Track 1: enterprise audit-universe fields ──────────────
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        help_text="Optional parent entity for hierarchy "
        "(e.g. Financial Operations → Accounts Payable Oversight).",
    )
    business_unit = models.ForeignKey(
        BusinessUnit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="auditable_entities",
    )
    entity_type = models.CharField(
        max_length=32,
        choices=EntityTypeChoices.choices,
        default=EntityTypeChoices.PROCESS,
    )
    primary_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_owned_entities",
    )
    secondary_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="secondary_owned_entities",
    )
    location = models.CharField(max_length=120, blank=True)
    audit_frequency = models.CharField(
        max_length=20,
        choices=AuditFrequencyChoices.choices,
        default=AuditFrequencyChoices.ANNUAL,
    )
    last_audit_rating = models.CharField(
        max_length=24,
        choices=LastAuditRatingChoices.choices,
        blank=True,
    )
    last_audit_period = models.CharField(max_length=32, blank=True)
    primary_language = models.CharField(max_length=8, blank=True, default="en")
    headcount = models.PositiveIntegerField(null=True, blank=True)
    operating_budget = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    estimated_man_days = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Estimated audit effort in man-days.",
    )
    is_mandatory_to_audit = models.BooleanField(default=False)
    cost_center_id = models.CharField(max_length=64, blank=True, db_index=True)
    tags = models.JSONField(default=list, blank=True)
    compliance_status = models.CharField(
        max_length=20,
        choices=ComplianceStatusChoices.choices,
        default=ComplianceStatusChoices.NOT_ASSESSED,
    )
    inherent_likelihood = models.PositiveSmallIntegerField(null=True, blank=True)
    inherent_impact = models.PositiveSmallIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)
    # Optimistic locking. Bumped on every save by the API serializer;
    # PATCH requests must include the current value or receive 409.
    version = models.PositiveIntegerField(default=1)

    # ── Locked-down enums (replacing free-text defaults) ───────────────
    risk_rating = models.CharField(
        max_length=20,
        choices=RiskRatingChoices.choices,
        default=RiskRatingChoices.MEDIUM,
    )
    last_audit_date = models.DateField(null=True, blank=True)
    next_audit_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=EntityStatusChoices.choices,
        default=EntityStatusChoices.ACTIVE,
    )

    # Phase 6 Track 2 — external system provenance. Identifies the
    # row when it was created (or last updated) from an inbound ERP
    # feed; idempotent upserts key off (external_source, external_id).
    external_source = models.CharField(max_length=64, blank=True, db_index=True)
    external_id = models.CharField(max_length=128, blank=True, db_index=True)

    # Default manager hides Archived rows; use ``all_objects`` to include them.
    objects = AuditableEntityActiveManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["external_source", "external_id"],
                condition=~models.Q(external_id=""),
                name="iams_auditable_entity_external_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["parent"], name="ae_parent_idx"),
            models.Index(fields=["business_unit", "status"], name="ae_bu_status_idx"),
            models.Index(fields=["department_ref", "status"], name="ae_dept_status_idx"),
            models.Index(fields=["risk_rating", "status"], name="ae_risk_status_idx"),
            models.Index(fields=["next_audit_date"], name="ae_next_audit_idx"),
            models.Index(fields=["primary_owner"], name="ae_primary_owner_idx"),
            models.Index(fields=["compliance_status"], name="ae_compliance_idx"),
        ]

    def __str__(self):
        return self.name


class BulkImportJob(TimeStampedModel):
    """One async ``AuditableEntity`` bulk-import request.

    A multipart upload to ``POST /api/auditable-entities/bulk-import/``
    creates a row in ``Pending`` and dispatches the Celery task. The
    worker parses CSV / XLSX, validates each row through the same
    serializer that backs single-entity writes, and updates the
    counters (``processed``, ``created``, ``updated``, ``skipped``).
    Per-row errors are stored in ``errors`` (first 200) so the UI can
    show actionable feedback.

    The job lifecycle is deliberately simple — no retries on the row
    level; a failed file is fixed and re-uploaded as a new job. The
    ``mode`` field controls transactional behaviour:

      - ``strict``  → all-or-nothing; one bad row fails the whole import
      - ``lenient`` → per-row savepoint; bad rows are skipped with an
                      error and the rest commit independently
    """

    STATUS_PENDING = "Pending"
    STATUS_VALIDATING = "Validating"
    STATUS_IMPORTING = "Importing"
    STATUS_COMPLETED = "Completed"
    STATUS_PARTIAL = "PartialSuccess"
    STATUS_FAILED = "Failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_VALIDATING, "Validating"),
        (STATUS_IMPORTING, "Importing"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_PARTIAL, "Partial success"),
        (STATUS_FAILED, "Failed"),
    ]

    MODE_STRICT = "strict"
    MODE_LENIENT = "lenient"
    MODE_CHOICES = [(MODE_STRICT, "Strict"), (MODE_LENIENT, "Lenient")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to="audit_universe/imports/%Y/%m/%d/")
    file_name = models.CharField(max_length=255, blank=True)
    mode = models.CharField(max_length=12, choices=MODE_CHOICES, default=MODE_LENIENT)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_universe_imports",
    )
    total_rows = models.PositiveIntegerField(default=0)
    processed = models.PositiveIntegerField(default=0)
    created = models.PositiveIntegerField(default=0)
    updated = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    errors = models.JSONField(
        default=list,
        help_text="Per-row error report. Each entry: "
        '{"row": int, "field": str, "message": str}.',
    )
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="bij_status_created_idx"),
        ]

    def __str__(self):
        return f"BulkImportJob {self.id} ({self.status})"


class AuditableEntityRevision(TimeStampedModel):
    """Append-only field-level change history for AuditableEntity.

    Distinct from the global ``AuditLogEntry`` (which captures CRUD
    metadata for any audited viewset): this table stores a structured
    diff per save so the Revisions tab on the entity detail page can
    render "Maria changed Risk Rating from Medium → High on 2026-04-12
    (Q1 review)". Save / delete are rejected after insert to preserve
    audit-trail integrity.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(
        AuditableEntity,
        on_delete=models.CASCADE,
        related_name="revisions",
    )
    version = models.PositiveIntegerField()
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_entity_revisions",
    )
    changes = models.JSONField(
        default=dict,
        help_text='Field-level diff: {"field": {"from": <old>, "to": <new>}}.',
    )
    comment = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["entity", "version"],
                name="iams_ae_revision_unique_version",
            ),
        ]
        indexes = [
            models.Index(fields=["entity", "-version"], name="ae_rev_entity_ver_idx"),
        ]

    def save(self, *args, **kwargs):
        # UUID PKs are populated by `default=` before save, so guard on
        # ``_state.adding`` rather than ``pk is not None``.
        if not self._state.adding:
            raise PermissionError(
                "AuditableEntityRevision is append-only; updates are not permitted."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError(
            "AuditableEntityRevision is append-only; deletes are not permitted."
        )


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


# ═════════════════════════════════════════════════════════════════════
# Phase 3 Track 2 — Quality Assurance & Improvement Program (QAIP)
#
# QAIP is the audit function auditing itself: it tracks internal /
# external / peer reviews of the internal audit team's own work,
# captures stakeholder satisfaction surveys, and measures the audit
# function's KPIs (timeliness, quality, coverage) against targets.
#
# IIA Standards 1300-series. The findings here are about the *audit
# function* — distinct from the regular ``Finding`` model which is
# about the *audited entities*.
# ═════════════════════════════════════════════════════════════════════


class QAIPAssessment(TimeStampedModel):
    """A quality assessment of the internal audit function (IIA 1310).

    Three flavors:
      - internal       — done quarterly/annually by the IA team itself
      - external       — required every 5 years by IIA Standard 1312
      - peer           — informal review by another IA department
      - post_engagement — per-engagement evaluation by stakeholders
    """

    TYPE_INTERNAL = "internal"
    TYPE_EXTERNAL = "external"
    TYPE_PEER = "peer"
    TYPE_POST_ENGAGEMENT = "post_engagement"
    TYPE_CHOICES = [
        (TYPE_INTERNAL, "Internal"),
        (TYPE_EXTERNAL, "External"),
        (TYPE_PEER, "Peer"),
        (TYPE_POST_ENGAGEMENT, "Post-engagement"),
    ]

    STATUS_PLANNED = "planned"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planned"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
    ]

    RATING_SATISFACTORY = "satisfactory"
    RATING_NEEDS_IMPROVEMENT = "needs_improvement"
    RATING_UNSATISFACTORY = "unsatisfactory"
    RATING_CHOICES = [
        (RATING_SATISFACTORY, "Satisfactory"),
        (RATING_NEEDS_IMPROVEMENT, "Needs Improvement"),
        (RATING_UNSATISFACTORY, "Unsatisfactory"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, db_index=True)
    period = models.CharField(
        max_length=32, db_index=True,
        help_text="Free-form period label (e.g. '2026', '2026-Q1', 'External-2026').",
    )
    lead_reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="qaip_assessments_led",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PLANNED, db_index=True
    )
    rating_overall = models.CharField(
        max_length=20, choices=RATING_CHOICES, blank=True,
        help_text="Set when status moves to Completed.",
    )
    scope = models.TextField(blank=True)
    methodology = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    started_at = models.DateField(null=True, blank=True)
    completed_at = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-period", "type"]
        indexes = [
            models.Index(fields=["type", "period"]),
            models.Index(fields=["status", "-period"]),
        ]


class QAIPFinding(TimeStampedModel):
    """A finding raised against the internal audit function itself.

    Distinct from ``Finding`` (which is raised against audited entities).
    Owners here are typically inside the IA team (Audit Manager, CAE).
    """

    RATING_CRITICAL = "critical"
    RATING_HIGH = "high"
    RATING_MEDIUM = "medium"
    RATING_LOW = "low"
    RATING_CHOICES = [
        (RATING_CRITICAL, "Critical"),
        (RATING_HIGH, "High"),
        (RATING_MEDIUM, "Medium"),
        (RATING_LOW, "Low"),
    ]

    STATUS_OPEN = "open"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_CLOSED, "Closed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(
        QAIPAssessment, on_delete=models.CASCADE, related_name="findings",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    rating = models.CharField(max_length=20, choices=RATING_CHOICES, db_index=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True
    )
    root_cause = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)
    owner = models.CharField(max_length=200, blank=True)
    owner_ref = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="qaip_findings_owned",
    )
    due_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["assessment_id", "rating", "due_date"]


class StakeholderSurvey(TimeStampedModel):
    """A satisfaction survey response from an audit stakeholder.

    Captured per-engagement (``audit`` FK) when post-audit, or
    standalone for annual stakeholder pulse surveys. ``respondent``
    may be left blank when ``anonymous=True``.
    """

    ROLE_AUDITEE = "auditee"
    ROLE_DEPT_HEAD = "department_head"
    ROLE_EXECUTIVE = "executive"
    ROLE_BOARD = "board_member"
    ROLE_AUDIT_COMMITTEE = "audit_committee"
    ROLE_EXTERNAL_AUDITOR = "external_auditor"
    ROLE_OTHER = "other"
    ROLE_CHOICES = [
        (ROLE_AUDITEE, "Auditee"),
        (ROLE_DEPT_HEAD, "Department Head"),
        (ROLE_EXECUTIVE, "Executive"),
        (ROLE_BOARD, "Board Member"),
        (ROLE_AUDIT_COMMITTEE, "Audit Committee"),
        (ROLE_EXTERNAL_AUDITOR, "External Auditor"),
        (ROLE_OTHER, "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit = models.ForeignKey(
        Audit, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="stakeholder_surveys",
    )
    respondent_role = models.CharField(
        max_length=32, choices=ROLE_CHOICES, default=ROLE_AUDITEE,
    )
    respondent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="qaip_survey_responses",
        help_text="Cleared automatically when anonymous=True.",
    )
    satisfaction_score = models.PositiveSmallIntegerField(
        help_text="1 (very dissatisfied) to 5 (very satisfied).",
    )
    feedback = models.TextField(blank=True)
    anonymous = models.BooleanField(default=False, db_index=True)
    submitted_at = models.DateTimeField()

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["audit", "-submitted_at"]),
            models.Index(fields=["respondent_role", "-submitted_at"]),
        ]
        constraints = [
            # Score is constrained at the DB level so a bad client can't
            # poison the average. ``Q`` works on Postgres + SQLite (3.37+).
            models.CheckConstraint(
                condition=models.Q(satisfaction_score__gte=1)
                & models.Q(satisfaction_score__lte=5),
                name="iams_qaip_survey_score_range",
            ),
        ]

    def save(self, *args, **kwargs):
        # Anonymous responses can't carry a respondent FK — clear it.
        if self.anonymous:
            self.respondent = None
        super().save(*args, **kwargs)


class AuditKPI(TimeStampedModel):
    """A measured KPI for the internal audit function.

    Variance is computed (``actual - target``) on read. We don't
    persist it so the value can't go stale relative to its inputs.
    """

    KIND_TIMELINESS = "timeliness"
    KIND_QUALITY = "quality"
    KIND_COVERAGE = "coverage"
    KIND_BUDGET = "budget_adherence"
    KIND_RESPONSE_RATE = "response_rate"
    KIND_REPORT_CYCLE = "report_cycle_days"
    KIND_CHOICES = [
        (KIND_TIMELINESS, "Timeliness"),
        (KIND_QUALITY, "Quality"),
        (KIND_COVERAGE, "Coverage"),
        (KIND_BUDGET, "Budget Adherence"),
        (KIND_RESPONSE_RATE, "Response Rate"),
        (KIND_REPORT_CYCLE, "Report Cycle (days)"),
    ]

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    DIRECTION_CHOICES = [
        (HIGHER_IS_BETTER, "Higher is better"),
        (LOWER_IS_BETTER, "Lower is better"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kpi_type = models.CharField(max_length=32, choices=KIND_CHOICES, db_index=True)
    period = models.CharField(
        max_length=32, db_index=True,
        help_text="Free-form period label (e.g. '2026-Q1', 'FY2026').",
    )
    target = models.DecimalField(max_digits=10, decimal_places=2)
    actual = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=20, blank=True, help_text="%, days, count, …")
    direction = models.CharField(
        max_length=20, choices=DIRECTION_CHOICES, default=HIGHER_IS_BETTER,
        help_text="Determines whether positive variance is good or bad.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-period", "kpi_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["kpi_type", "period"],
                name="iams_qaip_kpi_kind_period_unique",
            ),
        ]

    @property
    def variance(self):
        return self.actual - self.target

    @property
    def variance_is_favorable(self) -> bool:
        diff = self.variance
        if diff == 0:
            return True
        if self.direction == self.HIGHER_IS_BETTER:
            return diff > 0
        return diff < 0


# ═════════════════════════════════════════════════════════════════════
# Phase 3 Track 3 — Control Self-Assessment (CSA)
#
# Business units (auditees) self-evaluate their controls against a
# questionnaire authored by Internal Audit. The system auto-scores the
# response on submit, flags weak units (score < threshold) for next
# year's risk-based audit plan, and exposes an auditor-challenge
# workflow where IA reviewers can question specific answers.
#
# FR-CSA-01..05.
# ═════════════════════════════════════════════════════════════════════


class CSAQuestionnaire(TimeStampedModel):
    """The questionnaire IA publishes for business units to respond to.

    Reusable across many ``CSAResponse`` rows. Editing an active
    questionnaire is allowed; archiving it stops new responses from
    being created against it but keeps history viewable.
    """

    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    FRAMEWORK_COSO = "COSO"
    FRAMEWORK_COBIT = "COBIT"
    FRAMEWORK_ISO27001 = "ISO 27001"
    FRAMEWORK_CUSTOM = "Custom"
    FRAMEWORK_CHOICES = [
        (FRAMEWORK_COSO, "COSO"),
        (FRAMEWORK_COBIT, "COBIT"),
        (FRAMEWORK_ISO27001, "ISO 27001"),
        (FRAMEWORK_CUSTOM, "Custom"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    framework = models.CharField(max_length=30, choices=FRAMEWORK_CHOICES, default=FRAMEWORK_CUSTOM)
    version = models.CharField(max_length=20, default="1.0")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    description = models.TextField(blank=True)
    # Score below this threshold (out of 100) flags the responding entity
    # for next year's audit plan + dispatches a CSA_WEAK_CONTROL
    # notification to Audit Managers. Lives on the questionnaire so
    # different frameworks can have different bars.
    weak_threshold = models.PositiveIntegerField(
        default=60,
        help_text="Score (0-100) below which a response is flagged as a weak control.",
    )

    class Meta:
        ordering = ["-version", "title"]
        constraints = [
            models.UniqueConstraint(
                fields=["title", "version"],
                name="iams_csa_questionnaire_title_version_unique",
            ),
        ]


class CSAQuestion(TimeStampedModel):
    """One question on a questionnaire.

    Four response types:
      - yes_no            → boolean; "yes" = full weight, "no" = 0
      - scale_1_5         → 1..5 integer; score scales linearly to weight
      - text              → free-form; weight awarded if non-empty
      - evidence_required → free-form + must have ``evidence_file`` to score

    ``category`` lets the scoring split into design vs operating
    effectiveness (FR-CSA-03) — leave blank for an overall pool.
    """

    TYPE_YES_NO = "yes_no"
    TYPE_SCALE_1_5 = "scale_1_5"
    TYPE_TEXT = "text"
    TYPE_EVIDENCE_REQUIRED = "evidence_required"
    TYPE_CHOICES = [
        (TYPE_YES_NO, "Yes / No"),
        (TYPE_SCALE_1_5, "Scale 1-5"),
        (TYPE_TEXT, "Free text"),
        (TYPE_EVIDENCE_REQUIRED, "Free text + evidence file"),
    ]

    CATEGORY_DESIGN = "design"
    CATEGORY_OPERATING = "operating"
    CATEGORY_GENERAL = ""
    CATEGORY_CHOICES = [
        (CATEGORY_GENERAL, "General"),
        (CATEGORY_DESIGN, "Control design"),
        (CATEGORY_OPERATING, "Operating effectiveness"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    questionnaire = models.ForeignKey(
        CSAQuestionnaire, on_delete=models.CASCADE, related_name="questions",
    )
    control_id = models.CharField(
        max_length=50, blank=True,
        help_text="Free-form control reference (e.g. 'COSO-CC1.1').",
    )
    text = models.TextField()
    response_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default=TYPE_YES_NO)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=CATEGORY_GENERAL, blank=True)
    weight = models.PositiveIntegerField(
        default=1,
        help_text="Relative weight in the final score (must be ≥ 1).",
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["questionnaire_id", "order", "created_at"]
        indexes = [
            models.Index(fields=["questionnaire", "order"]),
        ]


class CSAResponse(TimeStampedModel):
    """One business unit's response to a questionnaire.

    Lifecycle:
      draft     — responder is filling it in; mutable
      submitted — responder finished; auto-scored; immutable except by
                  auditor challenge
      under_review — auditor has issued one or more challenges
      closed    — auditor has approved; row becomes read-only
    """

    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_UNDER_REVIEW = "under_review"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_UNDER_REVIEW, "Under Review"),
        (STATUS_CLOSED, "Closed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    questionnaire = models.ForeignKey(
        CSAQuestionnaire, on_delete=models.PROTECT, related_name="responses",
    )
    entity = models.ForeignKey(
        AuditableEntity, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="csa_responses",
    )
    department = models.CharField(max_length=200, blank=True)
    responder = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="csa_responses",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)

    # Computed on submit. Range 0..100. Split into design / operating
    # when questions carry those categories.
    score_overall = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    score_design = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    score_operating = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    is_weak = models.BooleanField(default=False, db_index=True)

    submitted_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-submitted_at", "-created_at"]
        indexes = [
            models.Index(fields=["questionnaire", "status"]),
            models.Index(fields=["entity", "-submitted_at"]),
        ]


class CSAAnswer(TimeStampedModel):
    """A single answer cell.

    ``value`` carries everything: "yes"/"no" for yes_no, "1".."5" for
    scale_1_5, plain text for text/evidence_required. The auditor
    challenge workflow lives here too — once a challenge is opened on
    an answer, the response moves to ``under_review`` and the responder
    can edit just this cell to address the challenge.
    """

    CHALLENGE_NONE = ""
    CHALLENGE_OPEN = "open"
    CHALLENGE_RESOLVED = "resolved"
    CHALLENGE_CHOICES = [
        (CHALLENGE_NONE, "None"),
        (CHALLENGE_OPEN, "Open"),
        (CHALLENGE_RESOLVED, "Resolved"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    response = models.ForeignKey(CSAResponse, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(CSAQuestion, on_delete=models.PROTECT, related_name="answers")
    value = models.TextField(blank=True)
    evidence_file = models.ForeignKey(
        EvidenceFile, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="csa_answers",
    )

    # Auditor challenge thread on this answer
    challenge_status = models.CharField(
        max_length=20, choices=CHALLENGE_CHOICES, default=CHALLENGE_NONE, blank=True, db_index=True
    )
    challenge_note = models.TextField(blank=True)
    challenged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="csa_challenges_opened",
    )
    challenged_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="csa_challenges_resolved",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["response_id", "question__order"]
        constraints = [
            models.UniqueConstraint(
                fields=["response", "question"],
                name="iams_csa_answer_response_question_unique",
            ),
        ]


# ═════════════════════════════════════════════════════════════════════
# Phase 3 Track 4 — Internal Control over Financial Reporting (ICFR)
#
# ICFR formalizes the design + operating-effectiveness testing of
# financial controls (SOX 404, COSO). Management performs an initial
# self-assessment; internal audit (or external auditors) test the same
# controls and may reach a different conclusion. Failed tests
# materialize as ``DeficiencyReport`` rows classified by severity
# (control deficiency / significant deficiency / material weakness).
#
# FR-ICFR-01..05.
# ═════════════════════════════════════════════════════════════════════


class Control(TimeStampedModel):
    """A documented internal control over financial reporting.

    Lives on a specific ``AuditableEntity`` (typically a process,
    cycle, or system). Each row is the *catalog* entry — actual testing
    instances are ``ControlTest`` rows below.
    """

    FRAMEWORK_SOX = "SOX"
    FRAMEWORK_COSO = "COSO"
    FRAMEWORK_COBIT = "COBIT"
    FRAMEWORK_CUSTOM = "Custom"
    FRAMEWORK_CHOICES = [
        (FRAMEWORK_SOX, "SOX"),
        (FRAMEWORK_COSO, "COSO"),
        (FRAMEWORK_COBIT, "COBIT"),
        (FRAMEWORK_CUSTOM, "Custom"),
    ]

    TYPE_PREVENTIVE = "preventive"
    TYPE_DETECTIVE = "detective"
    TYPE_CORRECTIVE = "corrective"
    TYPE_CHOICES = [
        (TYPE_PREVENTIVE, "Preventive"),
        (TYPE_DETECTIVE, "Detective"),
        (TYPE_CORRECTIVE, "Corrective"),
    ]

    NATURE_MANUAL = "manual"
    NATURE_AUTOMATED = "automated"
    NATURE_HYBRID = "hybrid"
    NATURE_CHOICES = [
        (NATURE_MANUAL, "Manual"),
        (NATURE_AUTOMATED, "Automated"),
        (NATURE_HYBRID, "Hybrid (IT-dependent manual)"),
    ]

    FREQUENCY_TRANSACTIONAL = "transactional"
    FREQUENCY_DAILY = "daily"
    FREQUENCY_WEEKLY = "weekly"
    FREQUENCY_MONTHLY = "monthly"
    FREQUENCY_QUARTERLY = "quarterly"
    FREQUENCY_ANNUAL = "annual"
    FREQUENCY_AD_HOC = "ad_hoc"
    FREQUENCY_CHOICES = [
        (FREQUENCY_TRANSACTIONAL, "Transactional"),
        (FREQUENCY_DAILY, "Daily"),
        (FREQUENCY_WEEKLY, "Weekly"),
        (FREQUENCY_MONTHLY, "Monthly"),
        (FREQUENCY_QUARTERLY, "Quarterly"),
        (FREQUENCY_ANNUAL, "Annual"),
        (FREQUENCY_AD_HOC, "Ad hoc"),
    ]

    STATUS_ACTIVE = "active"
    STATUS_RETIRED = "retired"
    STATUS_CHOICES = [(STATUS_ACTIVE, "Active"), (STATUS_RETIRED, "Retired")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(
        AuditableEntity, on_delete=models.CASCADE, related_name="icfr_controls",
    )
    control_id = models.CharField(
        max_length=50, db_index=True,
        help_text="Org-defined reference, e.g. 'AP-01' or 'FRC-13'.",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    framework = models.CharField(max_length=20, choices=FRAMEWORK_CHOICES, default=FRAMEWORK_SOX)
    control_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_PREVENTIVE)
    nature = models.CharField(max_length=20, choices=NATURE_CHOICES, default=NATURE_MANUAL)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default=FREQUENCY_MONTHLY)
    assertion = models.CharField(
        max_length=100, blank=True,
        help_text="Financial-statement assertion: existence, completeness, accuracy, valuation, …",
    )
    risk_rating = models.CharField(max_length=20, default="Medium")
    owner = models.CharField(max_length=200, blank=True)
    owner_ref = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="icfr_controls_owned",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)

    class Meta:
        ordering = ["entity_id", "control_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["entity", "control_id"],
                name="iams_icfr_control_entity_ref_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["framework", "control_type"]),
            models.Index(fields=["status", "risk_rating"]),
        ]


class ControlTest(TimeStampedModel):
    """One test instance of a Control for a specific period.

    Distinguishes **management assessment** (FR-ICFR-04) from **auditor
    assessment** — both can coexist with potentially different
    conclusions. The "official" record for SOX certification typically
    uses the auditor conclusion when present.
    """

    TEST_TYPE_DESIGN = "design"
    TEST_TYPE_OPERATING = "operating"
    TEST_TYPE_CHOICES = [
        (TEST_TYPE_DESIGN, "Test of Design"),
        (TEST_TYPE_OPERATING, "Test of Operating Effectiveness"),
    ]

    STATUS_PLANNED = "planned"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planned"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
    ]

    CONCLUSION_NOT_TESTED = "not_tested"
    CONCLUSION_EFFECTIVE = "effective"
    CONCLUSION_DEFICIENT = "deficient"
    CONCLUSION_CHOICES = [
        (CONCLUSION_NOT_TESTED, "Not Tested"),
        (CONCLUSION_EFFECTIVE, "Effective"),
        (CONCLUSION_DEFICIENT, "Deficient"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    control = models.ForeignKey(Control, on_delete=models.CASCADE, related_name="tests")
    period = models.CharField(max_length=32, db_index=True, help_text="e.g. 'FY2026-Q1'.")
    test_type = models.CharField(max_length=20, choices=TEST_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PLANNED, db_index=True)

    # Sampling
    planned_sample_size = models.PositiveIntegerField(default=0)
    sample_size = models.PositiveIntegerField(default=0)
    sample_method = models.CharField(max_length=100, blank=True)

    # Tester + reviewer
    tester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="icfr_tests_run",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="icfr_tests_reviewed",
    )

    # Dual conclusions (FR-ICFR-04 segregation)
    management_assessment = models.CharField(
        max_length=20, choices=CONCLUSION_CHOICES, default=CONCLUSION_NOT_TESTED,
        help_text="Process owner's self-assessment.",
    )
    management_assessment_notes = models.TextField(blank=True)
    auditor_assessment = models.CharField(
        max_length=20, choices=CONCLUSION_CHOICES, default=CONCLUSION_NOT_TESTED,
        help_text="Independent IA conclusion. Takes precedence in summary reports.",
    )
    auditor_assessment_notes = models.TextField(blank=True)

    started_at = models.DateField(null=True, blank=True)
    completed_at = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["control_id", "-period", "test_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["control", "period", "test_type"],
                name="iams_icfr_test_control_period_type_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["period", "status"]),
            models.Index(fields=["auditor_assessment"]),
        ]

    @property
    def conclusion(self) -> str:
        """Effective conclusion: auditor takes precedence when not_tested.

        SOX certification typically uses the IA team's assessment when
        present; management's stands as the official conclusion only
        when IA hasn't tested independently.
        """
        if self.auditor_assessment != self.CONCLUSION_NOT_TESTED:
            return self.auditor_assessment
        return self.management_assessment


class ControlException(TimeStampedModel):
    """An exception observed during a ControlTest's sample testing.

    Each row is one sample that failed (or surfaced an issue). Severity
    is independent of the deficiency classification — multiple
    exceptions can roll up into a single DeficiencyReport.
    """

    SEVERITY_LOW = "low"
    SEVERITY_MEDIUM = "medium"
    SEVERITY_HIGH = "high"
    SEVERITY_CHOICES = [
        (SEVERITY_LOW, "Low"),
        (SEVERITY_MEDIUM, "Medium"),
        (SEVERITY_HIGH, "High"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    test = models.ForeignKey(ControlTest, on_delete=models.CASCADE, related_name="exceptions")
    sample_ref = models.CharField(
        max_length=100, blank=True,
        help_text="Sample identifier — e.g. transaction ID or document number.",
    )
    description = models.TextField()
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default=SEVERITY_MEDIUM)
    evidence_files = models.ManyToManyField(
        EvidenceFile, blank=True, related_name="icfr_exceptions",
    )
    identified_at = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["test_id", "-identified_at"]
        indexes = [
            models.Index(fields=["test", "severity"]),
        ]


class DeficiencyReport(TimeStampedModel):
    """A formal deficiency raised on a failed ControlTest (FR-ICFR-03).

    Auto-created in draft when a ControlTest's auditor_assessment flips
    to ``deficient`` (see ``iams/icfr.py``).
    """

    CLASSIFICATION_CONTROL = "control_deficiency"
    CLASSIFICATION_SIGNIFICANT = "significant_deficiency"
    CLASSIFICATION_MATERIAL = "material_weakness"
    CLASSIFICATION_CHOICES = [
        (CLASSIFICATION_CONTROL, "Control Deficiency"),
        (CLASSIFICATION_SIGNIFICANT, "Significant Deficiency"),
        (CLASSIFICATION_MATERIAL, "Material Weakness"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_OPEN = "open"
    STATUS_REMEDIATING = "remediating"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_OPEN, "Open"),
        (STATUS_REMEDIATING, "Remediating"),
        (STATUS_CLOSED, "Closed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    test = models.OneToOneField(
        ControlTest, on_delete=models.CASCADE, related_name="deficiency",
    )
    classification = models.CharField(
        max_length=30, choices=CLASSIFICATION_CHOICES,
        default=CLASSIFICATION_CONTROL, db_index=True,
    )
    narrative = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)
    management_response = models.TextField(blank=True)
    identified_date = models.DateField(null=True, blank=True)
    target_resolution_date = models.DateField(null=True, blank=True)
    actual_resolution_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    owner = models.CharField(max_length=200, blank=True)
    owner_ref = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="icfr_deficiencies_owned",
    )

    class Meta:
        ordering = ["-identified_date", "classification"]
        indexes = [
            models.Index(fields=["classification", "status"]),
        ]


# ═════════════════════════════════════════════════════════════════════
# Phase 4 Track 1 — Configurable Risk Engine
#
# Pluggable scoring of ``AuditableEntity`` rows. The org defines a set
# of named ``RiskFactor`` rows (e.g. "Impact", "Likelihood", "Control
# Maturity") with min/max scales, then bundles them into one or more
# ``RiskScoringModel`` rows that pick a formula (weighted sum /
# weighted average / multiplicative). Each entity gets a per-model
# ``EntityRiskScore`` row that holds the factor values, the computed
# composite, the rank within the model, and a ``is_current`` flag so
# every recalculation produces a new immutable historical snapshot
# (FR-RISK-06) without losing the previous one.
#
# FR-RISK-01..10.
# ═════════════════════════════════════════════════════════════════════


class RiskFactor(TimeStampedModel):
    """A single rateable dimension of risk.

    ``code`` is a short slug used in factor_values JSON keys
    (e.g. ``"impact"``); ``name`` is the human label.
    Two reserved codes — ``impact`` and ``likelihood`` — are recognised
    by the heat-map endpoint.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.SlugField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    scale_min = models.PositiveSmallIntegerField(default=1)
    scale_max = models.PositiveSmallIntegerField(default=5)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(scale_max__gt=models.F("scale_min")),
                name="iams_risk_factor_scale_min_lt_max",
            ),
        ]


class RiskScoringModel(TimeStampedModel):
    """A named bundle of weighted factors + a formula.

    Only one model per ``name`` can be ``is_active=True`` at a time
    (DB-level partial-unique) so the auto-recompute signal has a
    deterministic answer to "which scoring model applies?".
    """

    FORMULA_WEIGHTED_SUM = "weighted_sum"
    FORMULA_WEIGHTED_AVG = "weighted_avg"
    FORMULA_MULTIPLICATIVE = "multiplicative"
    FORMULA_CHOICES = [
        (FORMULA_WEIGHTED_SUM, "Weighted sum"),
        (FORMULA_WEIGHTED_AVG, "Weighted average"),
        (FORMULA_MULTIPLICATIVE, "Multiplicative (likelihood × impact)"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    version = models.CharField(max_length=20, default="1.0")
    description = models.TextField(blank=True)
    formula = models.CharField(
        max_length=30, choices=FORMULA_CHOICES, default=FORMULA_WEIGHTED_SUM,
    )
    factors = models.ManyToManyField(
        RiskFactor, through="RiskFactorWeight", related_name="scoring_models",
    )
    # Score >= this → entity is auto-flagged as high-risk.
    # Expressed in normalized 0..100 space (the engine normalizes).
    high_risk_threshold = models.DecimalField(
        max_digits=5, decimal_places=2, default=70,
    )
    is_active = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["name", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "version"],
                name="iams_risk_model_name_version_unique",
            ),
            models.UniqueConstraint(
                fields=["name"],
                condition=models.Q(is_active=True),
                name="iams_risk_model_one_active_per_name",
            ),
        ]


class RiskFactorWeight(TimeStampedModel):
    """Per-scoring-model weight on a factor.

    The same ``RiskFactor`` can appear in many models with different
    weights (e.g. SOX-focused model weights Financial Exposure higher).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scoring_model = models.ForeignKey(
        RiskScoringModel, on_delete=models.CASCADE, related_name="factor_weights",
    )
    factor = models.ForeignKey(
        RiskFactor, on_delete=models.PROTECT, related_name="weights",
    )
    weight = models.DecimalField(max_digits=6, decimal_places=2, default=1)

    class Meta:
        ordering = ["scoring_model_id", "factor__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["scoring_model", "factor"],
                name="iams_risk_factor_weight_model_factor_unique",
            ),
        ]


class EntityRiskScore(TimeStampedModel):
    """One scoring instance for (entity, scoring_model) at a point in time.

    Append-only by convention: every recompute creates a new row and
    flips ``is_current=True`` on the new one, ``False`` on the previous.
    The partial unique constraint enforces a single current row per
    ``(entity, scoring_model)``.

    The ``factor_values`` JSON keys are the ``RiskFactor.code`` strings;
    values are integers in the factor's [scale_min, scale_max] range
    (validated by the scoring service).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(
        AuditableEntity, on_delete=models.CASCADE, related_name="risk_scores",
    )
    scoring_model = models.ForeignKey(
        RiskScoringModel, on_delete=models.PROTECT, related_name="entity_scores",
    )
    factor_values = models.JSONField(default=dict)
    composite_score = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    rank = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    is_high_risk = models.BooleanField(default=False, db_index=True)
    is_current = models.BooleanField(default=True, db_index=True)
    snapshot_at = models.DateTimeField()
    snapshot_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="risk_snapshots_taken",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-snapshot_at"]
        indexes = [
            models.Index(fields=["entity", "scoring_model", "-snapshot_at"]),
            models.Index(fields=["scoring_model", "is_current", "-composite_score"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["entity", "scoring_model"],
                condition=models.Q(is_current=True),
                name="iams_entity_risk_score_one_current",
            ),
        ]


# ═════════════════════════════════════════════════════════════════════
# Phase 4 Track 2 — Report Generation Engine
#
# A unified async report job: the FE POSTs a kind + parameters, the
# backend writes a ``ReportJob`` row in ``pending``, the Celery task
# picks it up, renders via the matching ``iams.reports.*`` renderer
# (PDF via WeasyPrint or Excel via openpyxl), stores the output as a
# ``FileField`` (MinIO in prod, local in dev), and sets status to
# ``completed``. Downloads are served via a signed-URL action that
# refuses while ``status != completed``.
#
# FR-RPT-01..07, FR-PLAN-05, FR-DASH-08, FR-QAIP-04, FR-ICFR-05.
# ═════════════════════════════════════════════════════════════════════


class ReportJob(TimeStampedModel):
    """One async report-generation request.

    ``kind`` is the canonical name of an ``iams.reports.*`` renderer
    (e.g. ``"audit_summary"``, ``"finding_trends"``). ``parameters`` is
    free-form JSON that the renderer interprets (period, audit_id,
    department, scoring_model_id, …).

    The output file is stored at ``reports/YYYY/MM/DD/{uuid}.{ext}``,
    served via the download action's signed URL when MinIO is wired
    (Phase 0 storage config), or a Django-served absolute URL otherwise.
    """

    KIND_AUDIT_SUMMARY = "audit_summary"
    KIND_FINDING_TRENDS = "finding_trends"
    KIND_CAP_STATUS = "cap_status"
    KIND_DEPARTMENT_RISK = "department_risk_profile"
    KIND_OPEN_ISSUES = "open_issues"
    KIND_ANNUAL_PLAN = "annual_audit_plan"
    KIND_ICFR_SUMMARY = "icfr_summary"
    KIND_QAIP_ANNUAL = "qaip_annual"
    KIND_AUDIT_COMMITTEE = "audit_committee_pack"
    KIND_FINDINGS_EXCEL = "findings_excel"
    KIND_CAPS_EXCEL = "caps_excel"
    KIND_TIME_ENTRIES_EXCEL = "time_entries_excel"
    KIND_CHOICES = [
        (KIND_AUDIT_SUMMARY, "Audit Summary"),
        (KIND_FINDING_TRENDS, "Finding Trends"),
        (KIND_CAP_STATUS, "CAP Status"),
        (KIND_DEPARTMENT_RISK, "Department Risk Profile"),
        (KIND_OPEN_ISSUES, "Open Issues"),
        (KIND_ANNUAL_PLAN, "Annual Audit Plan"),
        (KIND_ICFR_SUMMARY, "ICFR Summary"),
        (KIND_QAIP_ANNUAL, "QAIP Annual"),
        (KIND_AUDIT_COMMITTEE, "Audit Committee Pack"),
        (KIND_FINDINGS_EXCEL, "Findings Export (Excel)"),
        (KIND_CAPS_EXCEL, "CAPs Export (Excel)"),
        (KIND_TIME_ENTRIES_EXCEL, "Time Entries Export (Excel)"),
    ]

    FORMAT_PDF = "pdf"
    FORMAT_XLSX = "xlsx"
    FORMAT_CHOICES = [(FORMAT_PDF, "PDF"), (FORMAT_XLSX, "Excel")]

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=40, choices=KIND_CHOICES, db_index=True)
    output_format = models.CharField(max_length=10, choices=FORMAT_CHOICES, default=FORMAT_PDF)
    title = models.CharField(max_length=255, blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="report_jobs",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True,
    )
    output_file = models.FileField(
        upload_to="reports/%Y/%m/%d/", blank=True, null=True,
    )
    file_size_kb = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["requested_by", "-created_at"]),
            models.Index(fields=["kind", "status", "-created_at"]),
        ]


# ═════════════════════════════════════════════════════════════════════
# Phase 5 Track 1 — Security
#
# Login attempts, account lockouts, password history (no reuse of the
# last 5), and per-user TOTP devices. All on-prem; no SMS gateway.
# ═════════════════════════════════════════════════════════════════════
class LoginAttempt(TimeStampedModel):
    """Append-only ledger of every authentication attempt (FR-UAM-07).

    Records *every* login attempt — successful or not — with the request
    metadata we have at hand. ``username`` is stored even on failure so
    forensic queries can group attempts against a target account even
    when the user doesn't exist.
    """

    OUTCOME_SUCCESS = "success"
    OUTCOME_INVALID_CREDENTIALS = "invalid_credentials"
    OUTCOME_USER_NOT_FOUND = "user_not_found"
    OUTCOME_USER_INACTIVE = "user_inactive"
    OUTCOME_ACCOUNT_LOCKED = "account_locked"
    OUTCOME_MFA_REQUIRED = "mfa_required"
    OUTCOME_MFA_FAILED = "mfa_failed"
    OUTCOME_THROTTLED = "throttled"

    OUTCOME_CHOICES = [
        (OUTCOME_SUCCESS, "Success"),
        (OUTCOME_INVALID_CREDENTIALS, "Invalid credentials"),
        (OUTCOME_USER_NOT_FOUND, "User not found"),
        (OUTCOME_USER_INACTIVE, "User inactive"),
        (OUTCOME_ACCOUNT_LOCKED, "Account locked"),
        (OUTCOME_MFA_REQUIRED, "MFA required"),
        (OUTCOME_MFA_FAILED, "MFA failed"),
        (OUTCOME_THROTTLED, "Throttled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=255, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="login_attempts",
    )
    outcome = models.CharField(max_length=40, choices=OUTCOME_CHOICES, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    request_id = models.CharField(max_length=64, blank=True, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["username", "-timestamp"]),
            models.Index(fields=["outcome", "-timestamp"]),
            models.Index(fields=["ip_address", "-timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.username} {self.outcome} @ {self.timestamp:%Y-%m-%d %H:%M}"


class AccountLockout(TimeStampedModel):
    """An active lockout — present when an account is locked out (FR-UAM-04).

    We use one *row per lockout window* rather than a boolean on
    UserProfile so that:
      - the history of lockouts is auditable (forensic queries),
      - admin unlock just closes the row by setting ``cleared_at``,
      - the lockout window is bounded by ``locked_until`` for auto-clear.
    """

    REASON_FAILED_ATTEMPTS = "failed_attempts"
    REASON_ADMIN = "admin_action"
    REASON_SUSPECTED_COMPROMISE = "suspected_compromise"
    REASON_CHOICES = [
        (REASON_FAILED_ATTEMPTS, "Failed attempt threshold"),
        (REASON_ADMIN, "Administrative action"),
        (REASON_SUSPECTED_COMPROMISE, "Suspected compromise"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lockouts",
    )
    reason = models.CharField(max_length=40, choices=REASON_CHOICES, default=REASON_FAILED_ATTEMPTS)
    locked_at = models.DateTimeField(auto_now_add=True, db_index=True)
    locked_until = models.DateTimeField(null=True, blank=True, db_index=True)
    cleared_at = models.DateTimeField(null=True, blank=True)
    cleared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="lockouts_cleared",
    )
    failed_attempt_count = models.PositiveIntegerField(default=0)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-locked_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(cleared_at__isnull=True),
                name="iams_account_lockout_one_active",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-locked_at"]),
        ]

    def is_active(self) -> bool:
        from django.utils import timezone
        if self.cleared_at is not None:
            return False
        if self.locked_until and self.locked_until <= timezone.now():
            return False
        return True

    def __str__(self) -> str:
        active = "active" if self.is_active() else "cleared"
        return f"Lockout({self.user_id}, {self.reason}, {active})"


class PasswordHistory(TimeStampedModel):
    """Hashed history of past passwords for reuse prevention (FR-UAM-04).

    We keep the last N (default 5) hashes so the validator can reject a
    new password if it matches any of them via Django's password hasher
    ``check_password`` semantics.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="password_history",
    )
    password_hash = models.CharField(max_length=255)
    set_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-set_at"]
        indexes = [
            models.Index(fields=["user", "-set_at"]),
        ]

    def __str__(self) -> str:
        return f"PWHist({self.user_id}, {self.set_at:%Y-%m-%d})"


class MFADevice(TimeStampedModel):
    """A second-factor device registered for a user.

    For Phase 5 Track 1 we ship TOTP only (RFC 6238). The shared secret
    is stored encrypted-at-rest if ``SECRET_KEY`` is the standard
    Django key (Fernet wraps it transparently); other device kinds
    (WebAuthn, push) are reserved for future expansion.

    A user may have multiple devices — primary + backup codes are
    modeled as separate rows. ``confirmed=True`` only after the user
    has demonstrated possession by entering a valid token once.
    """

    KIND_TOTP = "totp"
    KIND_BACKUP_CODES = "backup_codes"
    KIND_CHOICES = [
        (KIND_TOTP, "TOTP authenticator"),
        (KIND_BACKUP_CODES, "Backup codes"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mfa_devices",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_TOTP)
    name = models.CharField(max_length=100, blank=True, help_text="User-facing label.")
    secret = models.CharField(max_length=255, help_text="Base32-encoded TOTP secret OR Fernet-encrypted backup-code JSON.")
    confirmed = models.BooleanField(default=False, db_index=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Exactly one confirmed TOTP device per user. Backup codes
            # are exempt — multiple rows are allowed.
            models.UniqueConstraint(
                fields=["user", "kind"],
                condition=models.Q(kind="totp", confirmed=True),
                name="iams_mfa_device_one_confirmed_totp",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "kind", "confirmed"]),
        ]

    def __str__(self) -> str:
        return f"MFA({self.user_id}, {self.kind}, confirmed={self.confirmed})"


# ═════════════════════════════════════════════════════════════════════
# Phase 6 Track 1 — Keycloak SSO
#
# When a user signs in via OIDC, the access token's ``groups`` claim
# carries the Keycloak groups the user belongs to. We map each group
# name (case-sensitive, full Keycloak path) to an IAMS Role; if a
# user is in multiple mapped groups the highest-precedence row wins.
# Lower ``precedence`` number = higher priority (so a "Super Admin"
# mapping at precedence 1 beats an "Auditor" mapping at precedence 10).
# ═════════════════════════════════════════════════════════════════════
class KeycloakGroupRoleMap(TimeStampedModel):
    """Maps a Keycloak group claim → IAMS Role for JIT provisioning.

    Editable in Django admin (no FE management UI yet — Phase 6 scope
    keeps the surface area tight). The OIDC backend reads this table on
    every SSO login so changes take effect on next sign-in.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group_name = models.CharField(
        max_length=255, unique=True,
        help_text="Full Keycloak group path, e.g. '/IAMS/Auditors'.",
    )
    role = models.ForeignKey(
        Role, on_delete=models.PROTECT, related_name="keycloak_mappings",
    )
    precedence = models.PositiveSmallIntegerField(
        default=10,
        help_text="Lower wins when a user is in multiple mapped groups.",
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["precedence", "group_name"]
        indexes = [
            models.Index(fields=["group_name", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.group_name} → {self.role.name} (p{self.precedence})"


# ═════════════════════════════════════════════════════════════════════
# Phase 6 Track 2 — ERP / HR Integrations
#
# Two flavors live in the same registry:
#   - **Inbound** sources push auditable_entity / finding rows into
#     IAMS via signed webhooks. The shared-secret HMAC keeps the
#     endpoint trustless.
#   - **Outbound** targets receive ``user`` payloads when IAMS users
#     are created or updated, so the HRIS/AD reflects the IA team
#     roster.
#
# A single ``IntegrationSource`` row can be both — e.g. Odoo as
# inbound entities + outbound user sync.
# ═════════════════════════════════════════════════════════════════════
class IntegrationSource(TimeStampedModel):
    """A registered external system IAMS exchanges data with."""

    KIND_SAP = "sap"
    KIND_ORACLE = "oracle"
    KIND_ODOO = "odoo"
    KIND_AD = "active_directory"
    KIND_HRIS = "hris"
    KIND_GENERIC = "generic"
    KIND_CHOICES = [
        (KIND_SAP, "SAP"),
        (KIND_ORACLE, "Oracle"),
        (KIND_ODOO, "Odoo"),
        (KIND_AD, "Active Directory"),
        (KIND_HRIS, "HRIS"),
        (KIND_GENERIC, "Generic"),
    ]

    STATUS_ACTIVE = "active"
    STATUS_PAUSED = "paused"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_ERROR, "Error"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128, unique=True)
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, default=KIND_GENERIC)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    # Inbound: webhook secret used to validate the HMAC-SHA256 signature
    # the caller posts in the ``X-IAMS-Signature`` header.
    inbound_enabled = models.BooleanField(default=False)
    inbound_secret = models.CharField(
        max_length=128, blank=True,
        help_text="HMAC-SHA256 secret used to verify inbound webhooks.",
    )
    # Outbound: target URL + bearer token to push user upserts to.
    outbound_enabled = models.BooleanField(default=False)
    outbound_url = models.URLField(blank=True)
    outbound_token = models.CharField(max_length=512, blank=True)
    outbound_pushes_users = models.BooleanField(default=False)
    last_inbound_at = models.DateTimeField(null=True, blank=True)
    last_outbound_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["kind", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.kind})"


class IntegrationEvent(TimeStampedModel):
    """One inbound or outbound event recorded for audit + retry.

    Inbound: every webhook delivery (success or failure) is rowed.
    Outbound: every user-push attempt is rowed. The audit committee
    can inspect this table to verify the integration story is
    delivering what the operator claims it is.
    """

    DIRECTION_INBOUND = "inbound"
    DIRECTION_OUTBOUND = "outbound"
    DIRECTION_CHOICES = [
        (DIRECTION_INBOUND, "Inbound"),
        (DIRECTION_OUTBOUND, "Outbound"),
    ]

    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(
        IntegrationSource, on_delete=models.CASCADE, related_name="events",
    )
    direction = models.CharField(max_length=16, choices=DIRECTION_CHOICES, db_index=True)
    resource_type = models.CharField(
        max_length=40, db_index=True,
        help_text="auditable_entity | finding | user | ...",
    )
    external_id = models.CharField(max_length=128, blank=True, db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, db_index=True)
    error = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["source", "-timestamp"]),
            models.Index(fields=["resource_type", "external_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.direction}:{self.resource_type}#{self.external_id} {self.status}"
