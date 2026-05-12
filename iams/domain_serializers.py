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
    NotificationPreference,
    RiskAssessmentImportIssue,
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
    class Meta:
        model = ApprovalStep
        fields = ["id", "role", "approver", "status", "date", "comments", "order"]


class ApprovalRequestSerializer(serializers.ModelSerializer):
    steps = ApprovalStepSerializer(many=True)

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
