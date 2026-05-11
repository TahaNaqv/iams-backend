import uuid
from django.conf import settings
from django.db import models


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
    lead_auditor = models.CharField(max_length=200)
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

    def __str__(self):
        return self.title


class Finding(TimeStampedModel):
    SEVERITY_CHOICES = [("Critical", "Critical"), ("High", "High"), ("Medium", "Medium"), ("Low", "Low")]
    STATUS_CHOICES = [("Open", "Open"), ("In Progress", "In Progress"), ("Resolved", "Resolved"), ("Closed", "Closed")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="findings")
    department = models.CharField(max_length=200)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default="Medium")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Open")
    owner = models.CharField(max_length=200)
    due_date = models.DateField()
    description = models.TextField(blank=True)
    root_cause = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)
    created_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-due_date", "title"]

    def __str__(self):
        return self.title


class CorrectiveAction(TimeStampedModel):
    STATUS_CHOICES = [("Open", "Open"), ("In Progress", "In Progress"), ("Overdue", "Overdue"), ("Closed", "Closed")]
    PRIORITY_CHOICES = [("High", "High"), ("Medium", "Medium"), ("Low", "Low")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    finding = models.ForeignKey(Finding, on_delete=models.CASCADE, related_name="corrective_actions")
    owner = models.CharField(max_length=200)
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Open")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="Medium")
    description = models.TextField(blank=True)
    progress = models.PositiveIntegerField(default=0)
    department = models.CharField(max_length=200)

    class Meta:
        ordering = ["-due_date", "title"]

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
    STATUS_CHOICES = [("Not Started", "Not Started"), ("In Progress", "In Progress"), ("Done", "Done")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="checklist_items")
    title = models.CharField(max_length=255)
    assignee = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Not Started")
    notes = models.TextField(blank=True)


class EvidenceFile(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="evidence_files")
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=100, blank=True)
    size_kb = models.PositiveIntegerField(default=0)
    uploaded_by = models.CharField(max_length=200, blank=True)
    uploaded_at = models.DateTimeField()


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
    owner = models.CharField(max_length=200, blank=True)
    risk_rating = models.CharField(max_length=20, default="Medium")
    last_audit_date = models.DateField(null=True, blank=True)
    next_audit_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=50, default="Active")


class RiskHistoryEntry(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.CharField(max_length=255)
    date = models.DateField()
    previous_rating = models.CharField(max_length=20)
    current_rating = models.CharField(max_length=20)
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-date"]


class Notification(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    message = models.TextField()
    type = models.CharField(max_length=50, default="info")
    read = models.BooleanField(default=False)
    timestamp = models.DateTimeField()

    class Meta:
        ordering = ["-timestamp"]


class AuditLogEntry(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.CharField(max_length=200)
    action = models.CharField(max_length=255)
    target = models.CharField(max_length=255)
    timestamp = models.DateTimeField()
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp"]


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
    author = models.CharField(max_length=200)
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
    sheet_name = models.CharField(max_length=255, blank=True)
    row_number = models.PositiveIntegerField(default=0)
    message = models.TextField()
