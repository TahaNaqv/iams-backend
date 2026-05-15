from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()

from iams.models import (
    ActivityItem,
    ApprovalChainTemplate,
    Audit,
    AuditAssignment,
    AuditableEntity,
    AuditableEntityRevision,
    AuditLogEntry,
    Auditor,
    BusinessUnit,
    ChecklistItem,
    Comment,
    CorrectiveAction,
    Department,
    EntityStatusChoices,
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
    Tag,
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


class BusinessUnitSummarySerializer(serializers.ModelSerializer):
    """Compact representation embedded inside other resources."""

    class Meta:
        model = BusinessUnit
        fields = ["id", "name", "code"]
        read_only_fields = fields


class BusinessUnitSerializer(serializers.ModelSerializer):
    riskAppetite = serializers.CharField(source="risk_appetite")
    parentId = serializers.PrimaryKeyRelatedField(
        source="parent",
        queryset=BusinessUnit.objects.all(),
        required=False,
        allow_null=True,
    )
    headId = serializers.PrimaryKeyRelatedField(
        source="head",
        queryset=User.objects.all(),
        required=False,
        allow_null=True,
    )
    departmentCount = serializers.SerializerMethodField()
    childCount = serializers.SerializerMethodField()

    class Meta:
        model = BusinessUnit
        fields = [
            "id",
            "name",
            "code",
            "headId",
            "parentId",
            "riskAppetite",
            "description",
            "departmentCount",
            "childCount",
        ]

    def get_departmentCount(self, obj):
        return obj.departments.count() if obj.pk else 0

    def get_childCount(self, obj):
        return obj.children.count() if obj.pk else 0

    def validate_parentId(self, value):
        if value and self.instance and value.pk == self.instance.pk:
            raise serializers.ValidationError("A business unit cannot be its own parent.")
        # Cycle check
        seen = set()
        node = value
        while node is not None:
            if node.pk in seen:
                raise serializers.ValidationError("Cycle detected in business-unit hierarchy.")
            if self.instance and node.pk == self.instance.pk:
                raise serializers.ValidationError(
                    "Setting this parent would create a cycle."
                )
            seen.add(node.pk)
            node = node.parent
        return value


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "slug", "color", "category", "description"]
        read_only_fields = ["id", "slug"]

    def create(self, validated_data):
        from django.utils.text import slugify
        validated_data.setdefault("slug", slugify(validated_data["name"]))
        return super().create(validated_data)


class DepartmentSerializer(serializers.ModelSerializer):
    riskRating = serializers.CharField(source="risk_rating", required=False)
    lastAuditDate = serializers.DateField(source="last_audit_date", allow_null=True, required=False)
    nextAuditDate = serializers.DateField(source="next_audit_date", allow_null=True, required=False)
    entityCount = serializers.IntegerField(source="entity_count", read_only=True)
    businessUnit = BusinessUnitSummarySerializer(source="business_unit", read_only=True)
    businessUnitId = serializers.PrimaryKeyRelatedField(
        source="business_unit",
        queryset=BusinessUnit.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )

    class Meta:
        model = Department
        fields = [
            "id",
            "name",
            "head",
            "riskRating",
            "lastAuditDate",
            "nextAuditDate",
            "entityCount",
            "businessUnit",
            "businessUnitId",
        ]


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


class UserSummarySerializer(serializers.Serializer):
    """Minimal user representation embedded in entity responses.

    Avoids leaking permission/role data; uses fields available on every
    auth backend (id, email, display name).
    """

    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    displayName = serializers.SerializerMethodField()

    def get_displayName(self, obj):
        full = (
            f"{getattr(obj, 'first_name', '')} {getattr(obj, 'last_name', '')}".strip()
        )
        return full or getattr(obj, "email", "") or str(obj)


class CurrentRiskScoreSummarySerializer(serializers.Serializer):
    """Lightweight nested representation of the entity's current EntityRiskScore."""

    compositeScore = serializers.FloatField(source="composite_score", read_only=True)
    rank = serializers.IntegerField(read_only=True)
    isHighRisk = serializers.SerializerMethodField()
    snapshotAt = serializers.DateTimeField(source="snapshot_at", read_only=True)

    def get_isHighRisk(self, obj):
        model = getattr(obj, "model", None)
        threshold = getattr(model, "high_risk_threshold", None) if model else None
        if threshold is None or obj.composite_score is None:
            return None
        try:
            return float(obj.composite_score) >= float(threshold)
        except (TypeError, ValueError):
            return None


class AuditableEntitySerializer(serializers.ModelSerializer):
    """Full read/write serializer for the audit universe.

    Read side embeds compact summaries for FK relationships so the FE
    can render badges without follow-up requests. Write side accepts
    ``*Id`` aliases for every FK and validates parent cycles,
    likelihood / impact ranges, and optimistic-locking ``version``.
    """

    # ── Identity & legacy compatibility ──
    riskRating = serializers.ChoiceField(
        source="risk_rating",
        choices=AuditableEntity._meta.get_field("risk_rating").choices,
    )
    entityType = serializers.ChoiceField(
        source="entity_type",
        choices=AuditableEntity._meta.get_field("entity_type").choices,
        required=False,
    )
    complianceStatus = serializers.ChoiceField(
        source="compliance_status",
        choices=AuditableEntity._meta.get_field("compliance_status").choices,
        required=False,
    )
    auditFrequency = serializers.ChoiceField(
        source="audit_frequency",
        choices=AuditableEntity._meta.get_field("audit_frequency").choices,
        required=False,
    )
    lastAuditRating = serializers.ChoiceField(
        source="last_audit_rating",
        choices=AuditableEntity._meta.get_field("last_audit_rating").choices,
        required=False,
        allow_blank=True,
    )
    lastAuditDate = serializers.DateField(source="last_audit_date", allow_null=True, required=False)
    nextAuditDate = serializers.DateField(source="next_audit_date", allow_null=True, required=False)
    lastAuditPeriod = serializers.CharField(source="last_audit_period", required=False, allow_blank=True)
    primaryLanguage = serializers.CharField(source="primary_language", required=False, allow_blank=True)
    operatingBudget = serializers.DecimalField(
        source="operating_budget",
        max_digits=18,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    isMandatoryToAudit = serializers.BooleanField(source="is_mandatory_to_audit", required=False)
    costCenterId = serializers.CharField(source="cost_center_id", required=False, allow_blank=True)
    inherentLikelihood = serializers.IntegerField(
        source="inherent_likelihood",
        required=False,
        allow_null=True,
        min_value=1,
        max_value=5,
    )
    inherentImpact = serializers.IntegerField(
        source="inherent_impact",
        required=False,
        allow_null=True,
        min_value=1,
        max_value=5,
    )

    # ── FK relations: nested read, *Id write ──
    department = serializers.CharField(read_only=False, required=False, allow_blank=True)
    departmentId = serializers.PrimaryKeyRelatedField(
        source="department_ref",
        queryset=Department.objects.all(),
        required=False,
        allow_null=True,
    )
    departmentRef = serializers.SerializerMethodField()
    businessUnitId = serializers.PrimaryKeyRelatedField(
        source="business_unit",
        queryset=BusinessUnit.objects.all(),
        required=False,
        allow_null=True,
    )
    businessUnit = BusinessUnitSummarySerializer(source="business_unit", read_only=True)
    parentId = serializers.PrimaryKeyRelatedField(
        source="parent",
        queryset=AuditableEntity.all_objects.all(),
        required=False,
        allow_null=True,
    )
    parent = serializers.SerializerMethodField()
    primaryOwnerId = serializers.PrimaryKeyRelatedField(
        source="primary_owner",
        queryset=User.objects.all(),
        required=False,
        allow_null=True,
    )
    primaryOwner = UserSummarySerializer(source="primary_owner", read_only=True)
    secondaryOwnerId = serializers.PrimaryKeyRelatedField(
        source="secondary_owner",
        queryset=User.objects.all(),
        required=False,
        allow_null=True,
    )
    secondaryOwner = UserSummarySerializer(source="secondary_owner", read_only=True)

    # ── Computed read fields ──
    childCount = serializers.SerializerMethodField()
    openAuditCount = serializers.SerializerMethodField()
    currentRiskScore = serializers.SerializerMethodField()
    lastRevisionAt = serializers.SerializerMethodField()
    inherentScore = serializers.SerializerMethodField()

    # ── Optimistic locking ──
    version = serializers.IntegerField(required=False)

    class Meta:
        model = AuditableEntity
        fields = [
            "id",
            "name",
            "description",
            "entityType",
            "status",
            "riskRating",
            "complianceStatus",
            "auditFrequency",
            "lastAuditRating",
            "lastAuditDate",
            "nextAuditDate",
            "lastAuditPeriod",
            "primaryLanguage",
            "location",
            "headcount",
            "operatingBudget",
            "isMandatoryToAudit",
            "costCenterId",
            "tags",
            "inherentLikelihood",
            "inherentImpact",
            "inherentScore",
            # legacy free-text
            "department",
            "owner",
            # FKs (read)
            "departmentRef",
            "businessUnit",
            "primaryOwner",
            "secondaryOwner",
            "parent",
            # FKs (write)
            "departmentId",
            "businessUnitId",
            "primaryOwnerId",
            "secondaryOwnerId",
            "parentId",
            # external provenance
            "external_source",
            "external_id",
            # computed
            "childCount",
            "openAuditCount",
            "currentRiskScore",
            "lastRevisionAt",
            "version",
        ]
        read_only_fields = ["id", "external_source", "external_id"]

    # ── Computed read fields ──
    def get_departmentRef(self, obj):
        ref = obj.department_ref
        if ref is None:
            return None
        return {"id": str(ref.id), "name": ref.name}

    def get_parent(self, obj):
        if obj.parent_id is None:
            return None
        return {"id": str(obj.parent_id), "name": obj.parent.name}

    def get_childCount(self, obj):
        if not obj.pk:
            return 0
        return obj.children.exclude(status=EntityStatusChoices.ARCHIVED).count()

    def get_openAuditCount(self, obj):
        if not obj.pk:
            return 0
        # Imported lazily to avoid circular imports
        from iams.models import Audit
        return Audit.objects.filter(
            department=obj.department or obj.department_ref.name if obj.department_ref else obj.department,
        ).exclude(status="Completed").count()

    def get_currentRiskScore(self, obj):
        if not obj.pk:
            return None
        current = obj.risk_scores.filter(is_current=True).first() if hasattr(obj, "risk_scores") else None
        if current is None:
            return None
        return CurrentRiskScoreSummarySerializer(current).data

    def get_lastRevisionAt(self, obj):
        if not obj.pk:
            return None
        rev = obj.revisions.order_by("-created_at").first()
        return rev.created_at if rev else None

    def get_inherentScore(self, obj):
        if obj.inherent_likelihood and obj.inherent_impact:
            return obj.inherent_likelihood * obj.inherent_impact
        return None

    # ── Validation ──
    def validate_tags(self, value):
        if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
            raise serializers.ValidationError("Tags must be a list of strings.")
        if len(value) > 50:
            raise serializers.ValidationError("At most 50 tags are allowed.")
        return value

    def validate_parentId(self, value):
        if value is None:
            return value
        if self.instance and value.pk == self.instance.pk:
            raise serializers.ValidationError("An entity cannot be its own parent.")
        seen = set()
        node = value
        while node is not None:
            if node.pk in seen:
                raise serializers.ValidationError("Cycle detected in entity hierarchy.")
            if self.instance and node.pk == self.instance.pk:
                raise serializers.ValidationError(
                    "Setting this parent would create a cycle."
                )
            seen.add(node.pk)
            node = node.parent
        return value

    def validate(self, attrs):
        last = attrs.get("last_audit_date") or (
            self.instance.last_audit_date if self.instance else None
        )
        nxt = attrs.get("next_audit_date") or (
            self.instance.next_audit_date if self.instance else None
        )
        if last and nxt and nxt < last:
            raise serializers.ValidationError({
                "nextAuditDate": "Next audit date cannot precede last audit date.",
            })

        # Optimistic locking: if `version` supplied on update, it must match.
        if self.instance is not None and "version" in attrs:
            supplied = attrs.pop("version")
            if supplied != self.instance.version:
                raise serializers.ValidationError({
                    "version": (
                        f"Stale version: server has {self.instance.version}, "
                        f"client sent {supplied}. Reload and re-apply your changes."
                    ),
                })
        elif "version" in attrs:
            # Ignore client-provided version on create.
            attrs.pop("version")
        return attrs

    def create(self, validated_data):
        # If FK is provided but legacy free-text isn't, populate it from the FK
        # for backward compatibility with consumers reading the old shape.
        dept_ref = validated_data.get("department_ref")
        if dept_ref and not validated_data.get("department"):
            validated_data["department"] = dept_ref.name
        instance = super().create(validated_data)
        return instance

    def update(self, instance, validated_data):
        dept_ref = validated_data.get("department_ref", instance.department_ref)
        if dept_ref and not validated_data.get("department") and not instance.department:
            validated_data["department"] = dept_ref.name
        # Bump version on every successful write
        validated_data["version"] = (instance.version or 0) + 1
        return super().update(instance, validated_data)


class AuditableEntityListSerializer(serializers.ModelSerializer):
    """Lighter projection for list / tree endpoints — skips heavy nested data."""

    riskRating = serializers.CharField(source="risk_rating")
    entityType = serializers.CharField(source="entity_type")
    complianceStatus = serializers.CharField(source="compliance_status")
    auditFrequency = serializers.CharField(source="audit_frequency")
    lastAuditDate = serializers.DateField(source="last_audit_date", allow_null=True)
    nextAuditDate = serializers.DateField(source="next_audit_date", allow_null=True)
    isMandatoryToAudit = serializers.BooleanField(source="is_mandatory_to_audit")
    parentId = serializers.UUIDField(source="parent_id", allow_null=True)
    departmentId = serializers.UUIDField(source="department_ref_id", allow_null=True)
    businessUnitId = serializers.UUIDField(source="business_unit_id", allow_null=True)
    primaryOwnerId = serializers.UUIDField(source="primary_owner_id", allow_null=True)
    inherentScore = serializers.SerializerMethodField()
    childCount = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = AuditableEntity
        fields = [
            "id",
            "name",
            # Legacy fields — retained on the wire until the drop migration
            # ships, so pre-Phase-7 clients (FE, contract tests, scripts)
            # continue to read the shape they expect.
            "department",
            "owner",
            "entityType",
            "status",
            "riskRating",
            "complianceStatus",
            "auditFrequency",
            "lastAuditDate",
            "nextAuditDate",
            "isMandatoryToAudit",
            "parentId",
            "departmentId",
            "businessUnitId",
            "primaryOwnerId",
            "tags",
            "inherentScore",
            "childCount",
            "version",
        ]
        read_only_fields = fields

    def get_inherentScore(self, obj):
        if obj.inherent_likelihood and obj.inherent_impact:
            return obj.inherent_likelihood * obj.inherent_impact
        return None


class AuditableEntityRevisionSerializer(serializers.ModelSerializer):
    entityId = serializers.UUIDField(source="entity_id", read_only=True)
    changedBy = UserSummarySerializer(source="changed_by", read_only=True)
    changedAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = AuditableEntityRevision
        fields = ["id", "entityId", "version", "changedBy", "changedAt", "changes", "comment"]
        read_only_fields = fields


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


# ──────────────────────────────────────────────────────────────────────
# Phase 4 Track 1 — Risk Engine serializers
# ──────────────────────────────────────────────────────────────────────
from iams.models import (  # noqa: E402
    EntityRiskScore,
    RiskFactor,
    RiskFactorWeight,
    RiskScoringModel,
)


class RiskFactorSerializer(serializers.ModelSerializer):
    scaleMin = serializers.IntegerField(source="scale_min", min_value=0)
    scaleMax = serializers.IntegerField(source="scale_max", min_value=1)
    isActive = serializers.BooleanField(source="is_active")

    class Meta:
        model = RiskFactor
        fields = ["id", "code", "name", "description", "scaleMin", "scaleMax", "isActive"]


class RiskFactorWeightSerializer(serializers.ModelSerializer):
    factorId = serializers.PrimaryKeyRelatedField(source="factor", queryset=RiskFactor.objects.all())
    factorCode = serializers.CharField(source="factor.code", read_only=True)
    factorName = serializers.CharField(source="factor.name", read_only=True)

    class Meta:
        model = RiskFactorWeight
        fields = ["id", "factorId", "factorCode", "factorName", "weight"]
        read_only_fields = ["factorCode", "factorName"]


class RiskScoringModelSerializer(serializers.ModelSerializer):
    highRiskThreshold = serializers.DecimalField(
        source="high_risk_threshold", max_digits=5, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("100"),
    )
    isActive = serializers.BooleanField(source="is_active")
    factorWeights = RiskFactorWeightSerializer(source="factor_weights", many=True, read_only=True)

    class Meta:
        model = RiskScoringModel
        fields = [
            "id", "name", "version", "description", "formula",
            "highRiskThreshold", "isActive", "factorWeights",
        ]
        read_only_fields = ["factorWeights"]


class EntityRiskScoreSerializer(serializers.ModelSerializer):
    entityId = serializers.PrimaryKeyRelatedField(source="entity", queryset=AuditableEntity.objects.all())
    entityName = serializers.CharField(source="entity.name", read_only=True)
    scoringModelId = serializers.PrimaryKeyRelatedField(
        source="scoring_model", queryset=RiskScoringModel.objects.all(),
    )
    scoringModelName = serializers.CharField(source="scoring_model.name", read_only=True)
    factorValues = serializers.JSONField(source="factor_values")
    compositeScore = serializers.DecimalField(
        source="composite_score", max_digits=6, decimal_places=2, read_only=True,
    )
    isHighRisk = serializers.BooleanField(source="is_high_risk", read_only=True)
    isCurrent = serializers.BooleanField(source="is_current", read_only=True)
    snapshotAt = serializers.DateTimeField(source="snapshot_at", read_only=True)
    snapshotById = serializers.UUIDField(source="snapshot_by_id", read_only=True, allow_null=True)

    class Meta:
        model = EntityRiskScore
        fields = [
            "id", "entityId", "entityName",
            "scoringModelId", "scoringModelName",
            "factorValues", "compositeScore",
            "rank", "isHighRisk", "isCurrent",
            "snapshotAt", "snapshotById", "notes",
        ]
        read_only_fields = [
            "entityName", "scoringModelName",
            "compositeScore", "rank", "isHighRisk", "isCurrent",
            "snapshotAt", "snapshotById",
        ]


# ──────────────────────────────────────────────────────────────────────
# Phase 4 Track 2 — Report Generation
# ──────────────────────────────────────────────────────────────────────
from iams.models import ReportJob  # noqa: E402


class ReportJobSerializer(serializers.ModelSerializer):
    requestedById = serializers.UUIDField(source="requested_by_id", read_only=True, allow_null=True)
    outputFormat = serializers.CharField(source="output_format", read_only=True)
    outputFile = serializers.SerializerMethodField()
    fileSizeKb = serializers.IntegerField(source="file_size_kb", read_only=True)
    startedAt = serializers.DateTimeField(source="started_at", read_only=True, allow_null=True)
    completedAt = serializers.DateTimeField(source="completed_at", read_only=True, allow_null=True)

    class Meta:
        model = ReportJob
        fields = [
            "id", "kind", "title", "outputFormat",
            "parameters", "status", "error",
            "requestedById",
            "outputFile", "fileSizeKb",
            "startedAt", "completedAt",
        ]
        read_only_fields = [
            "status", "error", "requestedById",
            "outputFile", "fileSizeKb",
            "startedAt", "completedAt", "outputFormat",
        ]

    def get_outputFile(self, obj) -> str | None:
        if not obj.output_file or obj.status != ReportJob.STATUS_COMPLETED:
            return None
        return obj.output_file.name  # the download endpoint resolves to a URL
