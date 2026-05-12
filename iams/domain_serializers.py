from rest_framework import serializers

from iams.models import (
    ActivityItem,
    ApprovalChainTemplate,
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
    NotificationPreference,
    RiskAssessmentImportIssue,
    WorkingPaper,
    RiskAssessmentMatrixCell,
    RiskAssessmentRecord,
    RiskAssessmentSheet,
    RiskAssessmentSummaryItem,
    RiskHistoryEntry,
    TimeEntry,
    TimelineEvent,
    ApprovalRequest,
    ApprovalStep,
    WorkProgram,
    WorkProcedure,
    WorkProcedureStep,
    AuditReport,
    AuditReportSection,
    ManagedDocument,
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


class ChecklistItemWriteSerializer(serializers.ModelSerializer):
    auditId = serializers.PrimaryKeyRelatedField(source="audit", queryset=Audit.objects.all())

    class Meta:
        model = ChecklistItem
        fields = ["id", "auditId", "title", "assignee", "status", "notes"]


class EvidenceFileSerializer(serializers.ModelSerializer):
    auditId = serializers.UUIDField(source="audit_id", read_only=True)
    sizeKb = serializers.IntegerField(source="size_kb")
    uploadedBy = serializers.CharField(source="uploaded_by")
    uploadedAt = serializers.DateTimeField(source="uploaded_at")
    scanStatus = serializers.CharField(source="scan_status", read_only=True)
    scanSignature = serializers.CharField(source="scan_signature", read_only=True)
    scannedAt = serializers.DateTimeField(source="scanned_at", read_only=True, allow_null=True)
    quarantined = serializers.BooleanField(read_only=True)

    class Meta:
        model = EvidenceFile
        fields = [
            "id", "auditId", "name", "type", "sizeKb", "uploadedBy", "uploadedAt",
            "scanStatus", "scanSignature", "scannedAt", "quarantined",
        ]


class TimelineEventSerializer(serializers.ModelSerializer):
    auditId = serializers.UUIDField(source="audit_id", read_only=True)

    class Meta:
        model = TimelineEvent
        fields = ["id", "auditId", "title", "description", "timestamp"]


class TimelineEventWriteSerializer(serializers.ModelSerializer):
    auditId = serializers.PrimaryKeyRelatedField(source="audit", queryset=Audit.objects.all())

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
    # ``description`` is the FE-conventional alias for the backend's
    # ``message`` field. Both names are emitted for compatibility while a
    # focused FE cleanup collapses the duplication.
    description = serializers.CharField(source="message", read_only=True)
    targetType = serializers.SerializerMethodField()
    targetId = serializers.UUIDField(source="target_object_id", read_only=True, allow_null=True)
    emailSentAt = serializers.DateTimeField(source="email_sent_at", read_only=True, allow_null=True)

    class Meta:
        model = Notification
        fields = [
            "id", "kind", "title", "message", "description",
            "type", "read", "timestamp", "link", "module",
            "targetType", "targetId", "emailSentAt",
        ]
        read_only_fields = fields

    def get_targetType(self, obj):
        ct = obj.target_content_type
        return ct.model if ct else None


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    inAppEnabled = serializers.BooleanField(source="in_app_enabled")
    emailEnabled = serializers.BooleanField(source="email_enabled")

    class Meta:
        model = NotificationPreference
        fields = ["id", "kind", "inAppEnabled", "emailEnabled"]
        read_only_fields = ["id"]


class AuditLogEntrySerializer(serializers.ModelSerializer):
    requestId = serializers.CharField(source="request_id", read_only=True)
    ipAddress = serializers.IPAddressField(source="ip_address", read_only=True, allow_null=True)
    userAgent = serializers.CharField(source="user_agent", read_only=True)
    targetType = serializers.SerializerMethodField()
    targetId = serializers.UUIDField(source="target_object_id", read_only=True, allow_null=True)

    class Meta:
        model = AuditLogEntry
        fields = [
            "id", "actor", "action", "target",
            "targetType", "targetId",
            "timestamp", "requestId", "ipAddress", "userAgent",
            "changes", "details",
        ]
        read_only_fields = fields

    def get_targetType(self, obj):
        ct = obj.target_content_type
        return ct.model if ct else None


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
    class Meta:
        model = RiskAssessmentImportIssue
        fields = ["id", "severity", "sheet", "cell", "message"]


class ApprovalStepSerializer(serializers.ModelSerializer):
    slaDays = serializers.IntegerField(source="sla_days", read_only=True)
    dueAt = serializers.DateTimeField(source="due_at", read_only=True, allow_null=True)
    escalatedAt = serializers.DateTimeField(source="escalated_at", read_only=True, allow_null=True)
    overdue = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalStep
        fields = [
            "id", "role", "approver", "status", "date", "comments", "order",
            "slaDays", "dueAt", "escalatedAt", "overdue",
        ]

    def get_overdue(self, obj) -> bool:
        from django.utils import timezone
        return bool(
            obj.status == "Pending" and obj.due_at is not None and obj.due_at < timezone.now()
        )


class ApprovalRequestSerializer(serializers.ModelSerializer):
    steps = ApprovalStepSerializer(many=True)
    lastActionAt = serializers.DateTimeField(source="last_action_at", read_only=True, allow_null=True)

    class Meta:
        model = ApprovalRequest
        fields = [
            "id",
            "title",
            "type",
            "reference_id",
            "department",
            "submitted_by",
            "submitted_date",
            "current_step",
            "priority",
            "description",
            "status",
            "steps",
            "lastActionAt",
        ]

    def create(self, validated_data):
        steps_data = validated_data.pop("steps", [])
        req = ApprovalRequest.objects.create(**validated_data)
        for i, s in enumerate(steps_data):
            step_order = s.pop("order", i)
            ApprovalStep.objects.create(request=req, order=step_order, **s)
        return req

    def update(self, instance, validated_data):
        # Basic update; steps are managed via workflow actions.
        for k, v in validated_data.items():
            if k != "steps":
                setattr(instance, k, v)
        instance.save()
        return instance


class ApprovalChainTemplateSerializer(serializers.ModelSerializer):
    requestType = serializers.CharField(source="request_type")
    isActive = serializers.BooleanField(source="is_active")

    class Meta:
        model = ApprovalChainTemplate
        fields = ["id", "name", "requestType", "chain", "description", "isActive"]


class WorkProcedureStepSerializer(serializers.ModelSerializer):
    procedureId = serializers.UUIDField(source="procedure_id", read_only=True)
    sampleSize = serializers.CharField(source="sample_size")
    completedBy = serializers.CharField(source="completed_by")
    completedDate = serializers.DateField(source="completed_date", allow_null=True)

    class Meta:
        model = WorkProcedureStep
        fields = ["id", "procedureId", "description", "method", "sampleSize", "result", "notes", "completedBy", "completedDate"]


class WorkProcedureStepWriteSerializer(serializers.ModelSerializer):
    procedureId = serializers.PrimaryKeyRelatedField(source="procedure", queryset=WorkProcedure.objects.all())
    sampleSize = serializers.CharField(source="sample_size", required=False, allow_blank=True)
    completedBy = serializers.CharField(source="completed_by", required=False, allow_blank=True)
    completedDate = serializers.DateField(source="completed_date", required=False, allow_null=True)

    class Meta:
        model = WorkProcedureStep
        fields = ["id", "procedureId", "description", "method", "sampleSize", "result", "notes", "completedBy", "completedDate"]


class WorkProcedureSerializer(serializers.ModelSerializer):
    workProgramId = serializers.UUIDField(source="work_program_id", read_only=True)
    riskArea = serializers.CharField(source="risk_area")
    controlRef = serializers.CharField(source="control_ref")
    assignedTo = serializers.CharField(source="assigned_to")
    signedOffBy = serializers.CharField(source="signed_off_by")
    signedOffDate = serializers.DateField(source="signed_off_date", allow_null=True)
    steps = WorkProcedureStepSerializer(many=True, read_only=True)

    class Meta:
        model = WorkProcedure
        fields = [
            "id",
            "workProgramId",
            "title",
            "objective",
            "riskArea",
            "controlRef",
            "assignedTo",
            "status",
            "conclusion",
            "signedOffBy",
            "signedOffDate",
            "steps",
        ]


class WorkProcedureWriteSerializer(serializers.ModelSerializer):
    workProgramId = serializers.PrimaryKeyRelatedField(source="work_program", queryset=WorkProgram.objects.all())
    riskArea = serializers.CharField(source="risk_area", required=False, allow_blank=True)
    controlRef = serializers.CharField(source="control_ref", required=False, allow_blank=True)
    assignedTo = serializers.CharField(source="assigned_to", required=False, allow_blank=True)
    signedOffBy = serializers.CharField(source="signed_off_by", required=False, allow_blank=True)
    signedOffDate = serializers.DateField(source="signed_off_date", required=False, allow_null=True)

    class Meta:
        model = WorkProcedure
        fields = [
            "id",
            "workProgramId",
            "title",
            "objective",
            "riskArea",
            "controlRef",
            "assignedTo",
            "status",
            "conclusion",
            "signedOffBy",
            "signedOffDate",
        ]


class WorkProgramSerializer(serializers.ModelSerializer):
    auditId = serializers.UUIDField(source="audit_id", read_only=True)
    auditTitle = serializers.CharField(source="audit.title", read_only=True)
    procedures = WorkProcedureSerializer(many=True, read_only=True)

    class Meta:
        model = WorkProgram
        fields = ["id", "auditId", "auditTitle", "title", "procedures"]


class WorkProgramWriteSerializer(serializers.ModelSerializer):
    auditId = serializers.PrimaryKeyRelatedField(source="audit", queryset=Audit.objects.all())

    class Meta:
        model = WorkProgram
        fields = ["id", "auditId", "title"]


class AuditReportSectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditReportSection
        fields = ["id", "order", "title", "type", "content"]


class AuditReportSerializer(serializers.ModelSerializer):
    auditId = serializers.UUIDField(source="audit_id", read_only=True)
    auditTitle = serializers.CharField(source="audit.title", read_only=True)
    createdDate = serializers.DateField(source="created_date", allow_null=True)
    lastModified = serializers.DateField(source="last_modified", allow_null=True)
    sections = AuditReportSectionSerializer(many=True, read_only=True)

    class Meta:
        model = AuditReport
        fields = [
            "id",
            "title",
            "auditId",
            "auditTitle",
            "status",
            "author",
            "reviewer",
            "createdDate",
            "lastModified",
            "department",
            "sections",
        ]


class AuditReportWriteSerializer(serializers.ModelSerializer):
    auditId = serializers.PrimaryKeyRelatedField(source="audit", queryset=Audit.objects.all())
    createdDate = serializers.DateField(source="created_date", required=False, allow_null=True)
    lastModified = serializers.DateField(source="last_modified", required=False, allow_null=True)

    class Meta:
        model = AuditReport
        fields = ["id", "title", "auditId", "status", "author", "reviewer", "createdDate", "lastModified", "department"]


class AuditReportSectionWriteSerializer(serializers.ModelSerializer):
    reportId = serializers.PrimaryKeyRelatedField(source="report", queryset=AuditReport.objects.all())

    class Meta:
        model = AuditReportSection
        fields = ["id", "reportId", "order", "title", "type", "content"]


class ManagedDocumentSerializer(serializers.ModelSerializer):
    fileType = serializers.CharField(source="file_type")
    fileSize = serializers.CharField(source="file_size")
    createdDate = serializers.DateField(source="created_date", allow_null=True)
    modifiedDate = serializers.DateField(source="modified_date", allow_null=True)
    downloadUrl = serializers.SerializerMethodField()
    scanStatus = serializers.CharField(source="scan_status", read_only=True)
    scanSignature = serializers.CharField(source="scan_signature", read_only=True)
    scannedAt = serializers.DateTimeField(source="scanned_at", read_only=True, allow_null=True)
    quarantined = serializers.BooleanField(read_only=True)

    class Meta:
        model = ManagedDocument
        fields = [
            "id",
            "title",
            "category",
            "status",
            "owner",
            "department",
            "fileType",
            "fileSize",
            "createdDate",
            "modifiedDate",
            "description",
            "tags",
            "versions",
            "downloadUrl",
            "scanStatus",
            "scanSignature",
            "scannedAt",
            "quarantined",
        ]

    def get_downloadUrl(self, obj):
        # Quarantined documents must not expose a download URL.
        if obj.quarantined or not obj.file:
            return None
        request = self.context.get("request")
        url = obj.file.url
        if request and not url.startswith(("http://", "https://")):
            url = request.build_absolute_uri(url)
        return url


class ManagedDocumentWriteSerializer(serializers.ModelSerializer):
    fileType = serializers.CharField(source="file_type", required=False, allow_blank=True)
    fileSize = serializers.CharField(source="file_size", required=False, allow_blank=True)
    createdDate = serializers.DateField(source="created_date", required=False, allow_null=True)
    modifiedDate = serializers.DateField(source="modified_date", required=False, allow_null=True)

    class Meta:
        model = ManagedDocument
        fields = [
            "id",
            "title",
            "category",
            "status",
            "owner",
            "department",
            "file",
            "fileType",
            "fileSize",
            "createdDate",
            "modifiedDate",
            "description",
            "tags",
            "versions",
        ]


class WorkingPaperSerializer(serializers.ModelSerializer):
    """Read serializer for working papers.

    Exposes engagement context (auditId/auditTitle), version chain
    metadata (parentId/isCurrentVersion), the sign-off pair (auditor +
    reviewer with timestamps and display names), AV scan state, and
    the cross-referenced finding IDs.
    """

    auditId = serializers.UUIDField(source="audit_id", read_only=True)
    auditTitle = serializers.CharField(source="audit.title", read_only=True)
    fileType = serializers.CharField(source="file_type")
    fileSizeKb = serializers.IntegerField(source="file_size_kb")

    parentId = serializers.UUIDField(source="parent_id", read_only=True, allow_null=True)
    isCurrentVersion = serializers.BooleanField(source="is_current_version", read_only=True)

    auditorSignedAt = serializers.DateTimeField(source="auditor_signed_at", read_only=True, allow_null=True)
    auditorSignedBy = serializers.SerializerMethodField()
    reviewerSignedAt = serializers.DateTimeField(source="reviewer_signed_at", read_only=True, allow_null=True)
    reviewerSignedBy = serializers.SerializerMethodField()
    signedOffAt = serializers.DateTimeField(source="signed_off_at", read_only=True, allow_null=True)
    isFinalized = serializers.SerializerMethodField()

    findingIds = serializers.PrimaryKeyRelatedField(
        source="findings", many=True,
        queryset=Finding.objects.all(),
        required=False,
    )

    scanStatus = serializers.CharField(source="scan_status", read_only=True)
    scanSignature = serializers.CharField(source="scan_signature", read_only=True)
    scannedAt = serializers.DateTimeField(source="scanned_at", read_only=True, allow_null=True)
    quarantined = serializers.BooleanField(read_only=True)

    class Meta:
        model = WorkingPaper
        fields = [
            "id", "auditId", "auditTitle", "reference", "title", "description",
            "file", "fileType", "fileSizeKb", "status",
            "parentId", "version", "isCurrentVersion",
            "auditorSignedAt", "auditorSignedBy",
            "reviewerSignedAt", "reviewerSignedBy",
            "signedOffAt", "isFinalized",
            "findingIds",
            "scanStatus", "scanSignature", "scannedAt", "quarantined",
        ]
        read_only_fields = [
            "auditId", "auditTitle",
            "version", "parentId", "isCurrentVersion",
            "auditorSignedAt", "reviewerSignedAt", "signedOffAt", "isFinalized",
            "scanStatus", "scanSignature", "scannedAt", "quarantined",
        ]

    def get_isFinalized(self, obj) -> bool:
        return obj.is_finalized()

    def _user_label(self, user) -> dict | None:
        if user is None:
            return None
        return {
            "id": str(user.pk),
            "email": user.email,
            "name": (user.get_full_name() or user.email).strip(),
        }

    def get_auditorSignedBy(self, obj):
        return self._user_label(obj.auditor_signed_by)

    def get_reviewerSignedBy(self, obj):
        return self._user_label(obj.reviewer_signed_by)


class WorkingPaperWriteSerializer(serializers.ModelSerializer):
    """Write serializer — POST creates new v1, PATCH updates draft state."""

    auditId = serializers.PrimaryKeyRelatedField(
        source="audit", queryset=Audit.objects.all(),
    )
    fileType = serializers.CharField(source="file_type", required=False, allow_blank=True)
    fileSizeKb = serializers.IntegerField(source="file_size_kb", required=False)
    findingIds = serializers.PrimaryKeyRelatedField(
        source="findings", many=True,
        queryset=Finding.objects.all(),
        required=False,
    )

    class Meta:
        model = WorkingPaper
        fields = [
            "id", "auditId", "reference", "title", "description",
            "file", "fileType", "fileSizeKb", "status", "findingIds",
        ]
        read_only_fields = ["id"]


# ──────────────────────────────────────────────────────────────────────
# Phase 3 Track 2 — QAIP
# ──────────────────────────────────────────────────────────────────────
from iams.models import AuditKPI, QAIPAssessment, QAIPFinding, StakeholderSurvey  # noqa: E402


class QAIPFindingSerializer(serializers.ModelSerializer):
    """Read+write serializer for QAIP findings.

    `assessmentId` is the FE-facing alias for the FK. `owner` stays as a
    free-text string for compatibility with the existing FE pattern;
    `ownerRef` exposes the optional User FK when it's populated by the
    server.
    """
    assessmentId = serializers.PrimaryKeyRelatedField(
        source="assessment", queryset=QAIPAssessment.objects.all(),
    )
    dueDate = serializers.DateField(source="due_date", allow_null=True, required=False)
    rootCause = serializers.CharField(source="root_cause", allow_blank=True, required=False)
    ownerRefId = serializers.UUIDField(source="owner_ref_id", read_only=True, allow_null=True)

    class Meta:
        model = QAIPFinding
        fields = [
            "id", "assessmentId", "title", "description", "rating", "status",
            "rootCause", "recommendation", "owner", "ownerRefId", "dueDate",
        ]


class QAIPAssessmentSerializer(serializers.ModelSerializer):
    """Top-level QAIP assessment with nested findings on read.

    Counts and aggregates are computed (not stored) — see the
    serializer methods — so they can't drift from the underlying rows.
    """
    leadReviewerId = serializers.PrimaryKeyRelatedField(
        source="lead_reviewer",
        queryset=__import__("django.contrib.auth", fromlist=["get_user_model"]).get_user_model().objects.all(),
        required=False, allow_null=True,
    )
    leadReviewerName = serializers.SerializerMethodField()
    ratingOverall = serializers.CharField(source="rating_overall", allow_blank=True, required=False)
    startedAt = serializers.DateField(source="started_at", allow_null=True, required=False)
    completedAt = serializers.DateField(source="completed_at", allow_null=True, required=False)

    # Computed counts
    findingsCount = serializers.SerializerMethodField()
    openFindingsCount = serializers.SerializerMethodField()
    findings = QAIPFindingSerializer(many=True, read_only=True)

    class Meta:
        model = QAIPAssessment
        fields = [
            "id", "title", "type", "period",
            "leadReviewerId", "leadReviewerName",
            "status", "ratingOverall",
            "scope", "methodology", "summary",
            "startedAt", "completedAt",
            "findingsCount", "openFindingsCount",
            "findings",
        ]
        read_only_fields = ["leadReviewerName", "findingsCount", "openFindingsCount", "findings"]

    def get_leadReviewerName(self, obj):
        u = obj.lead_reviewer
        if not u:
            return None
        return (u.get_full_name() or u.email or u.username).strip()

    def get_findingsCount(self, obj) -> int:
        # Use the prefetched cache when present to avoid an N+1 in list responses.
        if hasattr(obj, "_prefetched_objects_cache") and "findings" in obj._prefetched_objects_cache:
            return len(obj._prefetched_objects_cache["findings"])
        return obj.findings.count()

    def get_openFindingsCount(self, obj) -> int:
        if hasattr(obj, "_prefetched_objects_cache") and "findings" in obj._prefetched_objects_cache:
            return sum(1 for f in obj._prefetched_objects_cache["findings"] if f.status != "closed")
        return obj.findings.exclude(status="closed").count()


class StakeholderSurveySerializer(serializers.ModelSerializer):
    """Survey row serializer.

    When ``anonymous=True``, ``respondentId`` is forcibly NULL on
    output even if the model column happens to hold a value (defensive
    re-blanking — the model's ``save()`` already clears it but a
    legacy import could have bypassed save).
    """
    auditId = serializers.PrimaryKeyRelatedField(
        source="audit", queryset=Audit.objects.all(),
        required=False, allow_null=True,
    )
    respondentId = serializers.SerializerMethodField()
    respondentRole = serializers.CharField(source="respondent_role")
    satisfactionScore = serializers.IntegerField(source="satisfaction_score", min_value=1, max_value=5)
    submittedAt = serializers.DateTimeField(source="submitted_at")

    class Meta:
        model = StakeholderSurvey
        fields = [
            "id", "auditId", "respondentRole", "respondentId",
            "satisfactionScore", "feedback", "anonymous", "submittedAt",
        ]

    def get_respondentId(self, obj):
        if obj.anonymous or obj.respondent_id is None:
            return None
        return str(obj.respondent_id)


class AuditKPISerializer(serializers.ModelSerializer):
    """KPI row with computed variance on the wire."""
    kpiType = serializers.CharField(source="kpi_type")
    variance = serializers.SerializerMethodField()
    favorable = serializers.SerializerMethodField()

    class Meta:
        model = AuditKPI
        fields = [
            "id", "kpiType", "period", "target", "actual", "unit",
            "direction", "notes", "variance", "favorable",
        ]
        read_only_fields = ["variance", "favorable"]

    def get_variance(self, obj):
        return obj.variance

    def get_favorable(self, obj) -> bool:
        return obj.variance_is_favorable


# ──────────────────────────────────────────────────────────────────────
# Phase 3 Track 3 — CSA serializers
# ──────────────────────────────────────────────────────────────────────
from iams.models import (  # noqa: E402
    CSAAnswer,
    CSAQuestion,
    CSAQuestionnaire,
    CSAResponse,
)


class CSAQuestionSerializer(serializers.ModelSerializer):
    questionnaireId = serializers.PrimaryKeyRelatedField(
        source="questionnaire", queryset=CSAQuestionnaire.objects.all(),
    )
    controlId = serializers.CharField(source="control_id", allow_blank=True, required=False)
    responseType = serializers.CharField(source="response_type")

    class Meta:
        model = CSAQuestion
        fields = [
            "id", "questionnaireId", "controlId", "text",
            "responseType", "category", "weight", "order",
        ]


class CSAQuestionnaireSerializer(serializers.ModelSerializer):
    weakThreshold = serializers.IntegerField(source="weak_threshold", min_value=0, max_value=100)
    questions = CSAQuestionSerializer(many=True, read_only=True)
    questionCount = serializers.SerializerMethodField()

    class Meta:
        model = CSAQuestionnaire
        fields = [
            "id", "title", "framework", "version", "status",
            "description", "weakThreshold",
            "questions", "questionCount",
        ]
        read_only_fields = ["questions", "questionCount"]

    def get_questionCount(self, obj) -> int:
        if hasattr(obj, "_prefetched_objects_cache") and "questions" in obj._prefetched_objects_cache:
            return len(obj._prefetched_objects_cache["questions"])
        return obj.questions.count()


class CSAAnswerSerializer(serializers.ModelSerializer):
    responseId = serializers.PrimaryKeyRelatedField(
        source="response", queryset=CSAResponse.objects.all(),
    )
    questionId = serializers.PrimaryKeyRelatedField(
        source="question", queryset=CSAQuestion.objects.all(),
    )
    evidenceFileId = serializers.PrimaryKeyRelatedField(
        source="evidence_file", queryset=EvidenceFile.objects.all(),
        required=False, allow_null=True,
    )
    challengeStatus = serializers.CharField(source="challenge_status", read_only=True)
    challengeNote = serializers.CharField(source="challenge_note", read_only=True)
    challengedById = serializers.UUIDField(source="challenged_by_id", read_only=True, allow_null=True)
    challengedAt = serializers.DateTimeField(source="challenged_at", read_only=True, allow_null=True)
    resolutionNote = serializers.CharField(source="resolution_note", read_only=True)
    resolvedById = serializers.UUIDField(source="resolved_by_id", read_only=True, allow_null=True)
    resolvedAt = serializers.DateTimeField(source="resolved_at", read_only=True, allow_null=True)

    class Meta:
        model = CSAAnswer
        fields = [
            "id", "responseId", "questionId", "value", "evidenceFileId",
            "challengeStatus", "challengeNote", "challengedById", "challengedAt",
            "resolutionNote", "resolvedById", "resolvedAt",
        ]
        read_only_fields = [
            "challengeStatus", "challengeNote", "challengedById", "challengedAt",
            "resolutionNote", "resolvedById", "resolvedAt",
        ]


class CSAResponseSerializer(serializers.ModelSerializer):
    questionnaireId = serializers.PrimaryKeyRelatedField(
        source="questionnaire", queryset=CSAQuestionnaire.objects.all(),
    )
    questionnaireTitle = serializers.CharField(source="questionnaire.title", read_only=True)
    entityId = serializers.PrimaryKeyRelatedField(
        source="entity", queryset=AuditableEntity.objects.all(),
        required=False, allow_null=True,
    )
    entityName = serializers.CharField(source="entity.name", read_only=True, default=None)
    responderId = serializers.UUIDField(source="responder_id", read_only=True, allow_null=True)
    scoreOverall = serializers.DecimalField(
        source="score_overall", max_digits=5, decimal_places=2, read_only=True,
    )
    scoreDesign = serializers.DecimalField(
        source="score_design", max_digits=5, decimal_places=2, read_only=True, allow_null=True,
    )
    scoreOperating = serializers.DecimalField(
        source="score_operating", max_digits=5, decimal_places=2, read_only=True, allow_null=True,
    )
    isWeak = serializers.BooleanField(source="is_weak", read_only=True)
    submittedAt = serializers.DateTimeField(source="submitted_at", read_only=True, allow_null=True)
    closedAt = serializers.DateTimeField(source="closed_at", read_only=True, allow_null=True)
    answers = CSAAnswerSerializer(many=True, read_only=True)

    class Meta:
        model = CSAResponse
        fields = [
            "id", "questionnaireId", "questionnaireTitle",
            "entityId", "entityName", "department", "responderId",
            "status", "scoreOverall", "scoreDesign", "scoreOperating", "isWeak",
            "submittedAt", "closedAt",
            "answers",
        ]
        read_only_fields = [
            "questionnaireTitle", "entityName", "responderId",
            "status", "scoreOverall", "scoreDesign", "scoreOperating", "isWeak",
            "submittedAt", "closedAt", "answers",
        ]


# ──────────────────────────────────────────────────────────────────────
# Phase 3 Track 4 — ICFR serializers
# ──────────────────────────────────────────────────────────────────────
from iams.models import (  # noqa: E402
    Control,
    ControlException,
    ControlTest,
    DeficiencyReport,
)


class ControlSerializer(serializers.ModelSerializer):
    entityId = serializers.PrimaryKeyRelatedField(
        source="entity", queryset=AuditableEntity.objects.all(),
    )
    entityName = serializers.CharField(source="entity.name", read_only=True)
    controlId = serializers.CharField(source="control_id")
    controlType = serializers.CharField(source="control_type")
    riskRating = serializers.CharField(source="risk_rating")
    ownerRefId = serializers.UUIDField(source="owner_ref_id", read_only=True, allow_null=True)

    class Meta:
        model = Control
        fields = [
            "id", "entityId", "entityName", "controlId", "name", "description",
            "framework", "controlType", "nature", "frequency", "assertion",
            "riskRating", "owner", "ownerRefId", "status",
        ]
        read_only_fields = ["entityName", "ownerRefId"]


class ControlExceptionSerializer(serializers.ModelSerializer):
    testId = serializers.PrimaryKeyRelatedField(
        source="test", queryset=ControlTest.objects.all(),
    )
    sampleRef = serializers.CharField(source="sample_ref", allow_blank=True, required=False)
    identifiedAt = serializers.DateField(source="identified_at", allow_null=True, required=False)
    evidenceFileIds = serializers.PrimaryKeyRelatedField(
        source="evidence_files", many=True,
        queryset=EvidenceFile.objects.all(),
        required=False,
    )

    class Meta:
        model = ControlException
        fields = [
            "id", "testId", "sampleRef", "description", "severity",
            "evidenceFileIds", "identifiedAt",
        ]


class DeficiencyReportSerializer(serializers.ModelSerializer):
    testId = serializers.PrimaryKeyRelatedField(
        source="test", queryset=ControlTest.objects.all(),
    )
    controlId = serializers.CharField(source="test.control.control_id", read_only=True)
    controlName = serializers.CharField(source="test.control.name", read_only=True)
    period = serializers.CharField(source="test.period", read_only=True)
    managementResponse = serializers.CharField(source="management_response", allow_blank=True, required=False)
    identifiedDate = serializers.DateField(source="identified_date", allow_null=True, required=False)
    targetResolutionDate = serializers.DateField(source="target_resolution_date", allow_null=True, required=False)
    actualResolutionDate = serializers.DateField(source="actual_resolution_date", read_only=True, allow_null=True)
    ownerRefId = serializers.UUIDField(source="owner_ref_id", read_only=True, allow_null=True)

    class Meta:
        model = DeficiencyReport
        fields = [
            "id", "testId", "controlId", "controlName", "period",
            "classification", "narrative", "recommendation", "managementResponse",
            "identifiedDate", "targetResolutionDate", "actualResolutionDate",
            "status", "owner", "ownerRefId",
        ]
        read_only_fields = [
            "controlId", "controlName", "period",
            "actualResolutionDate", "ownerRefId",
        ]


class ControlTestSerializer(serializers.ModelSerializer):
    controlId = serializers.PrimaryKeyRelatedField(
        source="control", queryset=Control.objects.all(),
    )
    controlReference = serializers.CharField(source="control.control_id", read_only=True)
    controlName = serializers.CharField(source="control.name", read_only=True)
    testType = serializers.CharField(source="test_type")
    plannedSampleSize = serializers.IntegerField(source="planned_sample_size", required=False)
    sampleSize = serializers.IntegerField(source="sample_size", required=False)
    sampleMethod = serializers.CharField(source="sample_method", allow_blank=True, required=False)
    testerId = serializers.PrimaryKeyRelatedField(
        source="tester",
        queryset=__import__("django.contrib.auth", fromlist=["get_user_model"]).get_user_model().objects.all(),
        required=False, allow_null=True,
    )
    reviewerId = serializers.PrimaryKeyRelatedField(
        source="reviewer",
        queryset=__import__("django.contrib.auth", fromlist=["get_user_model"]).get_user_model().objects.all(),
        required=False, allow_null=True,
    )
    managementAssessment = serializers.CharField(source="management_assessment", required=False)
    managementAssessmentNotes = serializers.CharField(source="management_assessment_notes", allow_blank=True, required=False)
    auditorAssessment = serializers.CharField(source="auditor_assessment", required=False)
    auditorAssessmentNotes = serializers.CharField(source="auditor_assessment_notes", allow_blank=True, required=False)
    conclusion = serializers.SerializerMethodField()
    startedAt = serializers.DateField(source="started_at", allow_null=True, required=False)
    completedAt = serializers.DateField(source="completed_at", allow_null=True, required=False)
    exceptions = ControlExceptionSerializer(many=True, read_only=True)
    deficiency = DeficiencyReportSerializer(read_only=True)

    class Meta:
        model = ControlTest
        fields = [
            "id", "controlId", "controlReference", "controlName",
            "period", "testType", "status",
            "plannedSampleSize", "sampleSize", "sampleMethod",
            "testerId", "reviewerId",
            "managementAssessment", "managementAssessmentNotes",
            "auditorAssessment", "auditorAssessmentNotes",
            "conclusion",
            "startedAt", "completedAt",
            "exceptions", "deficiency",
        ]
        read_only_fields = [
            "controlReference", "controlName", "conclusion",
            "exceptions", "deficiency",
        ]

    def get_conclusion(self, obj) -> str:
        return obj.conclusion
