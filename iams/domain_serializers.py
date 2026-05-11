from rest_framework import serializers

from iams.models import (
    ActivityItem,
    Audit,
    AuditAssignment,
    AuditableEntity,
    AuditLogEntry,
    Auditor,
    ChecklistItem,
    Comment,
    CorrectiveAction,
    Department,
    EvidenceFile,
    Finding,
    FollowUpItem,
    HoursBudget,
    Notification,
    RiskAssessmentImportIssue,
    RiskAssessmentMatrixCell,
    RiskAssessmentRecord,
    RiskAssessmentSheet,
    RiskAssessmentSummaryItem,
    RiskHistoryEntry,
    TimeEntry,
    TimelineEvent,
)


class DepartmentSerializer(serializers.ModelSerializer):
    riskRating = serializers.CharField(source="risk_rating")
    lastAuditDate = serializers.DateField(source="last_audit_date", allow_null=True)
    nextAuditDate = serializers.DateField(source="next_audit_date", allow_null=True)
    entityCount = serializers.IntegerField(source="entity_count")

    class Meta:
        model = Department
        fields = ["id", "name", "head", "riskRating", "lastAuditDate", "nextAuditDate", "entityCount"]


class AuditSerializer(serializers.ModelSerializer):
    leadAuditor = serializers.CharField(source="lead_auditor")
    startDate = serializers.DateField(source="start_date")
    endDate = serializers.DateField(source="end_date")
    riskRating = serializers.CharField(source="risk_rating")
    completionPercent = serializers.IntegerField(source="completion_percent")
    findingsCount = serializers.IntegerField(source="findings_count")

    class Meta:
        model = Audit
        fields = [
            "id", "title", "department", "leadAuditor", "status", "startDate", "endDate",
            "priority", "riskRating", "scope", "objectives", "completionPercent", "findingsCount",
        ]


class FindingSerializer(serializers.ModelSerializer):
    auditId = serializers.UUIDField(source="audit_id", read_only=True)
    auditTitle = serializers.CharField(source="audit.title", read_only=True)
    dueDate = serializers.DateField(source="due_date")
    rootCause = serializers.CharField(source="root_cause", allow_blank=True)
    createdDate = serializers.DateField(source="created_date", allow_null=True)

    class Meta:
        model = Finding
        fields = [
            "id", "title", "auditId", "auditTitle", "department", "severity", "status",
            "owner", "dueDate", "description", "rootCause", "recommendation", "createdDate",
        ]


class FindingWriteSerializer(serializers.ModelSerializer):
    auditId = serializers.PrimaryKeyRelatedField(source="audit", queryset=Audit.objects.all())
    dueDate = serializers.DateField(source="due_date")
    rootCause = serializers.CharField(source="root_cause", allow_blank=True, required=False)
    createdDate = serializers.DateField(source="created_date", required=False, allow_null=True)

    class Meta:
        model = Finding
        fields = [
            "id", "title", "auditId", "department", "severity", "status", "owner", "dueDate",
            "description", "rootCause", "recommendation", "createdDate",
        ]


class CorrectiveActionSerializer(serializers.ModelSerializer):
    findingId = serializers.UUIDField(source="finding_id", read_only=True)
    findingTitle = serializers.CharField(source="finding.title", read_only=True)
    dueDate = serializers.DateField(source="due_date")

    class Meta:
        model = CorrectiveAction
        fields = [
            "id", "title", "findingId", "findingTitle", "owner", "dueDate", "status",
            "priority", "description", "progress", "department",
        ]


class CorrectiveActionWriteSerializer(serializers.ModelSerializer):
    findingId = serializers.PrimaryKeyRelatedField(source="finding", queryset=Finding.objects.all())
    dueDate = serializers.DateField(source="due_date")

    class Meta:
        model = CorrectiveAction
        fields = [
            "id", "title", "findingId", "owner", "dueDate", "status", "priority", "description", "progress", "department",
        ]


class ActivityItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivityItem
        fields = ["id", "action", "user", "target", "timestamp", "type"]


class ChecklistItemSerializer(serializers.ModelSerializer):
    auditId = serializers.UUIDField(source="audit_id", read_only=True)

    class Meta:
        model = ChecklistItem
        fields = ["id", "auditId", "title", "assignee", "status", "notes"]


class EvidenceFileSerializer(serializers.ModelSerializer):
    auditId = serializers.UUIDField(source="audit_id", read_only=True)
    sizeKb = serializers.IntegerField(source="size_kb")
    uploadedBy = serializers.CharField(source="uploaded_by")
    uploadedAt = serializers.DateTimeField(source="uploaded_at")

    class Meta:
        model = EvidenceFile
        fields = ["id", "auditId", "name", "type", "sizeKb", "uploadedBy", "uploadedAt"]


class TimelineEventSerializer(serializers.ModelSerializer):
    auditId = serializers.UUIDField(source="audit_id", read_only=True)

    class Meta:
        model = TimelineEvent
        fields = ["id", "auditId", "title", "description", "timestamp"]


class AuditableEntitySerializer(serializers.ModelSerializer):
    riskRating = serializers.CharField(source="risk_rating")
    lastAuditDate = serializers.DateField(source="last_audit_date", allow_null=True)
    nextAuditDate = serializers.DateField(source="next_audit_date", allow_null=True)

    class Meta:
        model = AuditableEntity
        fields = ["id", "name", "department", "owner", "riskRating", "lastAuditDate", "nextAuditDate", "status"]


class RiskHistoryEntrySerializer(serializers.ModelSerializer):
    previousRating = serializers.CharField(source="previous_rating")
    currentRating = serializers.CharField(source="current_rating")

    class Meta:
        model = RiskHistoryEntry
        fields = ["id", "entity", "date", "previousRating", "currentRating", "reason"]


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "title", "message", "type", "read", "timestamp"]


class AuditLogEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLogEntry
        fields = ["id", "actor", "action", "target", "timestamp", "details"]


class FollowUpItemSerializer(serializers.ModelSerializer):
    findingId = serializers.UUIDField(source="finding_id", read_only=True)
    dueDate = serializers.DateField(source="due_date")

    class Meta:
        model = FollowUpItem
        fields = ["id", "findingId", "owner", "dueDate", "status", "notes"]


class CommentSerializer(serializers.ModelSerializer):
    user = serializers.CharField(source="author")
    timestamp = serializers.DateTimeField(source="created_at")

    class Meta:
        model = Comment
        fields = ["id", "entity_id", "user", "text", "timestamp"]


class AuditorSerializer(serializers.ModelSerializer):
    weeklyCapacityHours = serializers.IntegerField(source="weekly_capacity_hours")

    class Meta:
        model = Auditor
        fields = ["id", "name", "email", "role", "availability", "skills", "certifications", "weeklyCapacityHours"]


class AuditAssignmentSerializer(serializers.ModelSerializer):
    auditorId = serializers.UUIDField(source="auditor_id", read_only=True)
    auditId = serializers.UUIDField(source="audit_id", read_only=True)
    startDate = serializers.DateField(source="start_date")
    endDate = serializers.DateField(source="end_date")

    class Meta:
        model = AuditAssignment
        fields = ["id", "auditorId", "auditId", "phase", "allocation_pct", "startDate", "endDate"]


class AuditAssignmentWriteSerializer(serializers.ModelSerializer):
    auditorId = serializers.PrimaryKeyRelatedField(source="auditor", queryset=Auditor.objects.all())
    auditId = serializers.PrimaryKeyRelatedField(source="audit", queryset=Audit.objects.all())
    startDate = serializers.DateField(source="start_date")
    endDate = serializers.DateField(source="end_date")

    class Meta:
        model = AuditAssignment
        fields = ["id", "auditorId", "auditId", "phase", "allocation_pct", "startDate", "endDate"]


class TimeEntrySerializer(serializers.ModelSerializer):
    auditorId = serializers.UUIDField(source="auditor_id", read_only=True)
    auditId = serializers.UUIDField(source="audit_id", read_only=True)

    class Meta:
        model = TimeEntry
        fields = ["id", "auditorId", "auditId", "date", "hours", "status", "notes"]


class TimeEntryWriteSerializer(serializers.ModelSerializer):
    auditorId = serializers.PrimaryKeyRelatedField(source="auditor", queryset=Auditor.objects.all())
    auditId = serializers.PrimaryKeyRelatedField(source="audit", queryset=Audit.objects.all())

    class Meta:
        model = TimeEntry
        fields = ["id", "auditorId", "auditId", "date", "hours", "status", "notes"]


class HoursBudgetSerializer(serializers.ModelSerializer):
    auditId = serializers.UUIDField(source="audit_id", read_only=True)
    budgetedHours = serializers.IntegerField(source="budgeted_hours")
    consumedHours = serializers.IntegerField(source="consumed_hours")

    class Meta:
        model = HoursBudget
        fields = ["id", "auditId", "budgetedHours", "consumedHours"]


class HoursBudgetWriteSerializer(serializers.ModelSerializer):
    auditId = serializers.PrimaryKeyRelatedField(source="audit", queryset=Audit.objects.all())
    budgetedHours = serializers.IntegerField(source="budgeted_hours")
    consumedHours = serializers.IntegerField(source="consumed_hours")

    class Meta:
        model = HoursBudget
        fields = ["id", "auditId", "budgetedHours", "consumedHours"]


class RiskAssessmentSheetSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskAssessmentSheet
        fields = ["id", "name", "description", "order"]


class RiskAssessmentRecordSerializer(serializers.ModelSerializer):
    sourceSheet = serializers.CharField(source="source_sheet")
    sourceRow = serializers.IntegerField(source="source_row")
    riskArea = serializers.CharField(source="risk_area")
    riskDescription = serializers.CharField(source="risk_description")
    inherentRisk = serializers.CharField(source="inherent_risk")
    existingControls = serializers.CharField(source="existing_controls")
    controlEffectiveness = serializers.CharField(source="control_effectiveness")
    residualRisk = serializers.CharField(source="residual_risk")
    auditObjective = serializers.CharField(source="audit_objective")
    auditSteps = serializers.CharField(source="audit_steps")
    documentsRequired = serializers.CharField(source="documents_required")
    inclusionStatus = serializers.CharField(source="inclusion_status")
    auditScope = serializers.CharField(source="audit_scope")
    plannedManDays = serializers.DecimalField(source="planned_man_days", max_digits=6, decimal_places=2)

    class Meta:
        model = RiskAssessmentRecord
        fields = [
            "id", "sheet", "sourceSheet", "sourceRow", "department", "objective", "riskArea", "riskDescription",
            "grading", "likelihood", "impact", "inherentRisk", "existingControls", "controlEffectiveness", "residualRisk",
            "auditObjective", "auditSteps", "documentsRequired", "inclusionStatus", "auditScope", "plannedManDays", "notes",
        ]


class RiskAssessmentMatrixCellSerializer(serializers.ModelSerializer):
    residualRisk = serializers.CharField(source="residual_risk")

    class Meta:
        model = RiskAssessmentMatrixCell
        fields = ["id", "likelihood", "impact", "residualRisk"]


class RiskAssessmentSummaryItemSerializer(serializers.ModelSerializer):
    recordId = serializers.UUIDField(source="record_id", read_only=True)
    inclusionStatus = serializers.CharField(source="inclusion_status")
    auditScope = serializers.CharField(source="audit_scope")
    plannedManDays = serializers.DecimalField(source="planned_man_days", max_digits=6, decimal_places=2)

    class Meta:
        model = RiskAssessmentSummaryItem
        fields = ["id", "recordId", "inclusionStatus", "auditScope", "plannedManDays"]


class RiskAssessmentImportIssueSerializer(serializers.ModelSerializer):
    sheetName = serializers.CharField(source="sheet_name")
    rowNumber = serializers.IntegerField(source="row_number")

    class Meta:
        model = RiskAssessmentImportIssue
        fields = ["id", "severity", "sheetName", "rowNumber", "message"]
