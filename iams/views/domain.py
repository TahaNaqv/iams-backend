from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from iams.domain_serializers import (
    ActivityItemSerializer,
    AuditAssignmentSerializer,
    AuditAssignmentWriteSerializer,
    AuditLogEntrySerializer,
    AuditSerializer,
    AuditableEntityListSerializer,
    AuditableEntityRevisionSerializer,
    AuditableEntitySerializer,
    AuditorSerializer,
    BulkImportJobSerializer,
    EntityRiskSerializer,
    BusinessUnitSerializer,
    ChecklistItemSerializer,
    ChecklistItemWriteSerializer,
    CommentSerializer,
    CorrectiveActionSerializer,
    CorrectiveActionWriteSerializer,
    DepartmentSerializer,
    EvidenceFileSerializer,
    FindingSerializer,
    FindingWriteSerializer,
    FollowUpItemSerializer,
    HoursBudgetSerializer,
    HoursBudgetWriteSerializer,
    ApprovalChainTemplateSerializer,
    NotificationPreferenceSerializer,
    NotificationSerializer,
    RiskAssessmentImportIssueSerializer,
    RiskAssessmentMatrixCellSerializer,
    RiskAssessmentRecordSerializer,
    RiskAssessmentSheetSerializer,
    RiskAssessmentSummaryItemSerializer,
    RiskHistoryEntrySerializer,
    TagSerializer,
    ApprovalRequestSerializer,
    WorkProgramSerializer,
    WorkProgramWriteSerializer,
    WorkProcedureSerializer,
    WorkProcedureWriteSerializer,
    WorkProcedureStepSerializer,
    WorkProcedureStepWriteSerializer,
    AuditReportSerializer,
    AuditReportWriteSerializer,
    AuditReportSectionSerializer,
    AuditReportSectionWriteSerializer,
    ManagedDocumentSerializer,
    ManagedDocumentWriteSerializer,
    TimeEntrySerializer,
    TimeEntryWriteSerializer,
    TimelineEventSerializer,
    TimelineEventWriteSerializer,
)
from iams.models import (
    ActivityItem,
    Audit,
    AuditAssignment,
    AuditLogEntry,
    AuditableEntity,
    AuditableEntityRevision,
    Auditor,
    BulkImportJob,
    BusinessUnit,
    ChecklistItem,
    Comment,
    EntityRisk,
    CorrectiveAction,
    Department,
    EntityStatusChoices,
    EvidenceFile,
    Finding,
    FollowUpItem,
    HoursBudget,
    ApprovalChainTemplate,
    Notification,
    NotificationPreference,
    RiskAssessmentImportIssue,
    RiskAssessmentMatrixCell,
    RiskAssessmentRecord,
    RiskAssessmentSheet,
    RiskAssessmentSummaryItem,
    RiskHistoryEntry,
    Tag,
    ApprovalRequest,
    WorkProgram,
    WorkProcedure,
    WorkProcedureStep,
    AuditReport,
    AuditReportSection,
    ManagedDocument,
    WorkingPaper,
    TimeEntry,
    TimelineEvent,
)
from iams.audit import AuditedViewSetMixin
from iams.filters import (
    AuditableEntityFilter,
    BusinessUnitFilter,
    DepartmentFilter,
    TagFilter,
)
from iams.permissions import HasPermission


class AuditViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = Audit.objects.all()
    serializer_class = AuditSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [HasPermission("view_audits")]
        if self.action == "create":
            return [HasPermission("create_audits")]
        if self.action in ("update", "partial_update"):
            return [HasPermission("edit_audits")]
        if self.action == "destroy":
            return [HasPermission("delete_audits")]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get("search")
        status_filter = self.request.query_params.get("status")
        department = self.request.query_params.get("department")
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(scope__icontains=search))
        if status_filter:
            qs = qs.filter(status=status_filter)
        if department:
            qs = qs.filter(department=department)
        return qs


class FindingViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = Finding.objects.select_related("audit").all()
    permission_classes = [HasPermission("manage_findings")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return FindingWriteSerializer
        return FindingSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        audit_id = self.request.query_params.get("audit_id")
        if audit_id:
            qs = qs.filter(audit_id=audit_id)
        return qs


class CorrectiveActionViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = CorrectiveAction.objects.select_related("finding", "finding__audit").all()
    permission_classes = [HasPermission("manage_caps")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return CorrectiveActionWriteSerializer
        return CorrectiveActionSerializer


class DepartmentViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = Department.objects.all().select_related("business_unit").order_by("name", "id")
    serializer_class = DepartmentSerializer
    filterset_class = DepartmentFilter
    search_fields = ["name", "head"]
    ordering_fields = ["name", "risk_rating", "last_audit_date", "next_audit_date", "entity_count"]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated(), HasPermission("view_audits")()]
        return [IsAuthenticated(), HasPermission("edit_audits")()]


class ActivityViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ActivityItem.objects.all()
    serializer_class = ActivityItemSerializer
    permission_classes = [IsAuthenticated]


class ChecklistByAuditView(APIView):
    permission_classes = [HasPermission("view_audits")]

    def get(self, request, audit_id):
        items = ChecklistItem.objects.filter(audit_id=audit_id)
        return Response(ChecklistItemSerializer(items, many=True).data)

    def post(self, request, audit_id):
        self.check_permissions(request)
        if not HasPermission("edit_audits").has_permission(request, self):
            return Response(status=status.HTTP_403_FORBIDDEN)
        serializer = ChecklistItemWriteSerializer(data={**request.data, "auditId": str(audit_id)})
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        return Response(ChecklistItemSerializer(item).data, status=status.HTTP_201_CREATED)


class ChecklistItemViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = ChecklistItem.objects.all().order_by("created_at", "id")
    serializer_class = ChecklistItemSerializer

    def get_permissions(self):
        # Reads: anyone with view_audits. Writes: edit_audits.
        if self.action in ("list", "retrieve"):
            return [HasPermission("view_audits")]
        return [HasPermission("edit_audits")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return ChecklistItemWriteSerializer
        return ChecklistItemSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        audit_id = self.request.query_params.get("audit_id")
        if audit_id:
            qs = qs.filter(audit_id=audit_id)
        return qs


class EvidenceByAuditView(APIView):
    permission_classes = [HasPermission("view_audits")]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, audit_id):
        items = EvidenceFile.objects.filter(audit_id=audit_id)
        return Response(EvidenceFileSerializer(items, many=True).data)

    def post(self, request, audit_id):
        self.check_permissions(request)
        if not HasPermission("edit_audits").has_permission(request, self):
            return Response(status=status.HTTP_403_FORBIDDEN)
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response({"detail": "file is required"}, status=status.HTTP_400_BAD_REQUEST)
        now = timezone.now()
        item = EvidenceFile.objects.create(
            audit_id=audit_id,
            file=uploaded_file,
            name=request.data.get("name") or uploaded_file.name,
            type=request.data.get("type") or uploaded_file.content_type or "",
            size_kb=int(uploaded_file.size / 1024),
            uploaded_by=request.data.get("uploadedBy") or (getattr(request.user, "email", "") or ""),
            uploaded_at=now,
        )
        # Dispatch AV scan asynchronously — the upload returns immediately
        # with scan_status='pending'; the FE polls the row to see when the
        # scan finishes (or relies on the WebSocket push planned for Phase 5).
        from iams.tasks import scan_uploaded_file
        scan_uploaded_file.delay(model_label="EvidenceFile", object_id=str(item.id))
        return Response(EvidenceFileSerializer(item).data, status=status.HTTP_201_CREATED)


class EvidenceFileViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = EvidenceFile.objects.all().order_by("-uploaded_at", "id")
    serializer_class = EvidenceFileSerializer
    permission_classes = [HasPermission("view_audits")]

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        """Return a download URL.

        Quarantined files (failed AV scan, scan error, or oversized) refuse
        the download with 403 — the row remains visible (so reviewers know
        something was uploaded) but the bytes are unreachable.

        When the storage backend supports it (MinIO/S3), this returns a
        signed URL with a short expiry; for local FileSystemStorage in dev
        it falls back to an absolute media URL.
        """
        obj = self.get_object()
        if obj.quarantined:
            return Response(
                {
                    "detail": "File is quarantined.",
                    "scanStatus": obj.scan_status,
                    "scanSignature": obj.scan_signature,
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        if obj.scan_status == EvidenceFile.SCAN_PENDING:
            return Response(
                {"detail": "File is still being scanned.", "scanStatus": obj.scan_status},
                status=status.HTTP_409_CONFLICT,
            )
        if not obj.file:
            return Response({"detail": "No file available."}, status=status.HTTP_404_NOT_FOUND)
        # ``file.url`` already produces a signed URL when django-storages is
        # configured with ``querystring_auth=True`` (see settings.prod). For
        # local FileSystemStorage we wrap it in the request host.
        url = obj.file.url
        if not url.startswith(("http://", "https://")):
            url = request.build_absolute_uri(url)
        return Response({"url": url})


class TimelineByAuditView(APIView):
    permission_classes = [HasPermission("view_audits")]

    def get(self, request, audit_id):
        items = TimelineEvent.objects.filter(audit_id=audit_id)
        return Response(TimelineEventSerializer(items, many=True).data)

    def post(self, request, audit_id):
        self.check_permissions(request)
        if not HasPermission("edit_audits").has_permission(request, self):
            return Response(status=status.HTTP_403_FORBIDDEN)
        serializer = TimelineEventWriteSerializer(data={**request.data, "auditId": str(audit_id)})
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        return Response(TimelineEventSerializer(item).data, status=status.HTTP_201_CREATED)


class AuditableEntityViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """Writable audit-universe API.

    Defaults to the active set (``status != Archived``); use
    ``?status=Archived`` or ``?includeArchived=true`` to see archived
    rows. Soft-delete via the dedicated ``archive`` action — DELETE
    against this resource also performs a soft-delete to preserve the
    audit trail downstream.

    Deprecation note: the response body still includes the pre-Phase-7
    free-text ``owner`` and ``department`` fields for backward compat.
    Both will be removed in a future major release; new consumers
    should bind to ``primaryOwnerId`` / ``primaryOwner`` and
    ``departmentId`` / ``departmentRef`` respectively.
    """

    serializer_class = AuditableEntitySerializer
    filterset_class = AuditableEntityFilter
    search_fields = [
        "name",
        "description",
        "cost_center_id",
        "department",
        "department_ref__name",
        "business_unit__name",
    ]
    ordering_fields = [
        "name",
        "risk_rating",
        "compliance_status",
        "last_audit_date",
        "next_audit_date",
        "headcount",
        "operating_budget",
        "created_at",
        "updated_at",
    ]
    ordering = ["name", "id"]

    # Map every action to a permission code so the role matrix is auditable.
    _ACTION_PERMISSIONS: dict[str, str] = {
        "list": "view_audits",
        "retrieve": "view_audits",
        "tree": "view_audits",
        "lineage": "view_audits",
        "revisions": "view_audits",
        "coverage": "view_audits",
        "kpis": "view_audits",
        "export": "view_audits",
        "create": "create_audits",
        "bulk_import": "create_audits",
        "clone": "create_audits",
        "update": "edit_audits",
        "partial_update": "edit_audits",
        "bulk_update": "edit_audits",
        "archive": "edit_audits",
        "restore": "edit_audits",
        "recompute": "edit_audits",
        "reset_risk_overrides": "edit_audits",
        "destroy": "edit_audits",
    }

    def get_permissions(self):
        perm = self._ACTION_PERMISSIONS.get(self.action, "view_audits")
        return [IsAuthenticated(), HasPermission(perm)()]

    def finalize_response(self, request, response, *args, **kwargs):
        # Surface a RFC-8594-style ``Deprecation`` header on every read
        # response. Consumers (and external monitors) can spot which
        # clients still pull the legacy ``owner`` / ``department``
        # CharFields by alerting on this header in their logs.
        response = super().finalize_response(request, response, *args, **kwargs)
        if self.action in ("list", "retrieve", "tree", "lineage", "revisions"):
            response["Deprecation"] = (
                'fields="owner,department"; sunset="next-major"'
            )
        return response

    def get_queryset(self):
        include_archived = self.request.query_params.get("includeArchived", "").lower() in (
            "1",
            "true",
            "yes",
        )
        explicit_status = self.request.query_params.get("status")
        manager = AuditableEntity.all_objects if (include_archived or explicit_status) else AuditableEntity.objects
        qs = manager.all().select_related(
            "department_ref",
            "business_unit",
            "primary_owner",
            "secondary_owner",
            "parent",
        )
        # Annotate child count for tree-aware list views, plus the count
        # of attached risks (drives the Risk Register's per-engagement view).
        qs = qs.annotate(
            _child_count=Count(
                "children",
                filter=~Q(children__status=EntityStatusChoices.ARCHIVED),
                distinct=True,
            ),
            _risk_count=Count("risks", distinct=True),
        )
        return qs

    def get_serializer_class(self):
        if self.action in ("list", "tree"):
            # Lighter projection for list/tree to reduce payload size.
            requested = self.request.query_params.get("fields")
            if requested != "full":
                return AuditableEntityListSerializer
        return AuditableEntitySerializer

    # ─── Revision capture ─────────────────────────────────────────────
    # Tracked fields whose changes appear in the immutable
    # AuditableEntityRevision diff. Excludes timestamps, version, and
    # mirror columns derived from FKs.
    _REVISION_TRACKED_FIELDS = (
        "name",
        "description",
        "entity_type",
        "status",
        "risk_rating",
        "compliance_status",
        "audit_frequency",
        "last_audit_rating",
        "last_audit_date",
        "next_audit_date",
        "last_audit_period",
        "primary_language",
        "location",
        "headcount",
        "operating_budget",
        "estimated_man_days",
        "is_mandatory_to_audit",
        "cost_center_id",
        "tags",
        "inherent_likelihood",
        "inherent_impact",
        "department_ref_id",
        "business_unit_id",
        "primary_owner_id",
        "secondary_owner_id",
        "parent_id",
    )

    @staticmethod
    def _capture_field_values(instance):
        snapshot = {}
        for f in AuditableEntityViewSet._REVISION_TRACKED_FIELDS:
            value = getattr(instance, f, None)
            # Stringify UUID/Date/Decimal for JSON-safe storage.
            if value is None or isinstance(value, (str, int, float, bool, list, dict)):
                snapshot[f] = value
            else:
                snapshot[f] = str(value)
        return snapshot

    def _record_revision(self, instance, before, comment=""):
        after = self._capture_field_values(instance)
        diff = {}
        for key, new_val in after.items():
            old_val = before.get(key) if before is not None else None
            if old_val != new_val:
                diff[key] = {"from": old_val, "to": new_val}
        if not diff and before is not None:
            # No-op save (e.g. an idempotent PATCH); skip a noisy revision.
            return
        AuditableEntityRevision.objects.create(
            entity=instance,
            version=instance.version or 1,
            changed_by=self.request.user if self.request.user.is_authenticated else None,
            changes=diff if before is not None else {"_initial": after},
            comment=comment,
        )

    def perform_create(self, serializer):
        instance = serializer.save()
        self._record_revision(instance, before=None, comment="Created.")
        self._bump_metric("created")

    def perform_update(self, serializer):
        before = self._capture_field_values(serializer.instance)
        instance = serializer.save()
        self._record_revision(instance, before=before)
        self._bump_metric("updated")

    @staticmethod
    def _bump_metric(action_name: str) -> None:
        """Increment a Phase-7 counter, tolerating import / metrics failures.

        The metrics module is imported lazily so that a partial test
        environment without prometheus_client (or with a misconfigured
        registry) doesn't break the write path. The same defensive
        pattern is used elsewhere in the codebase (see views that touch
        ``report_jobs_*`` counters).
        """
        try:
            from iams import metrics as m
            if action_name == "created":
                m.audit_universe_entities_created_total.inc()
            elif action_name == "updated":
                m.audit_universe_entities_updated_total.inc()
            elif action_name == "archived":
                m.audit_universe_entities_archived_total.inc()
        except Exception:  # noqa: BLE001 - metrics must never break a write
            pass

    # ─── Soft-delete semantics ────────────────────────────────────────
    def perform_destroy(self, instance):
        before = self._capture_field_values(instance)
        instance.status = EntityStatusChoices.ARCHIVED
        instance.version = (instance.version or 0) + 1
        instance.save(update_fields=["status", "version", "updated_at"])
        self._record_revision(instance, before=before, comment="Archived (DELETE).")
        self._bump_metric("archived")

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, pk=None):
        instance = self.get_object()
        if instance.status == EntityStatusChoices.ARCHIVED:
            return Response(
                {"detail": "Entity is already archived."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        before = self._capture_field_values(instance)
        instance.status = EntityStatusChoices.ARCHIVED
        instance.version = (instance.version or 0) + 1
        instance.save(update_fields=["status", "version", "updated_at"])
        self._record_revision(instance, before=before, comment="Archived.")
        self._bump_metric("archived")
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        try:
            instance = AuditableEntity.all_objects.get(pk=pk)
        except AuditableEntity.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if instance.status != EntityStatusChoices.ARCHIVED:
            return Response(
                {"detail": "Entity is not archived."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        before = self._capture_field_values(instance)
        instance.status = EntityStatusChoices.ACTIVE
        instance.version = (instance.version or 0) + 1
        instance.save(update_fields=["status", "version", "updated_at"])
        self._record_revision(instance, before=before, comment="Restored.")
        return Response(self.get_serializer(instance).data)

    # ─── Hierarchy ────────────────────────────────────────────────────
    @action(detail=False, methods=["get"], url_path="tree")
    def tree(self, request):
        """Returns a nested-tree projection.

        Query params:
          ``root`` (uuid)  — start the tree at a specific entity (default: top-level)
          ``depth`` (int)  — max depth, default 5 (capped at 10)
          standard filters from ``AuditableEntityFilter`` also apply.
        """
        try:
            depth = min(int(request.query_params.get("depth", 5)), 10)
        except (TypeError, ValueError):
            depth = 5
        root_id = request.query_params.get("root")

        qs = self.filter_queryset(self.get_queryset())
        all_rows = list(qs)
        by_parent: dict = {}
        for row in all_rows:
            by_parent.setdefault(row.parent_id, []).append(row)

        def build(node, level):
            data = AuditableEntityListSerializer(node).data
            if level >= depth:
                data["children"] = []
            else:
                data["children"] = [build(c, level + 1) for c in by_parent.get(node.id, [])]
            return data

        if root_id:
            root = get_object_or_404(AuditableEntity.all_objects, pk=root_id)
            return Response([build(root, 0)])
        roots = by_parent.get(None, [])
        return Response([build(r, 0) for r in roots])

    @action(detail=True, methods=["get"], url_path="lineage")
    def lineage(self, request, pk=None):
        """Returns the ancestor chain for breadcrumb rendering."""
        instance = self.get_object()
        chain: list = []
        node = instance.parent
        seen = set()
        while node is not None and node.id not in seen:
            chain.append({"id": str(node.id), "name": node.name})
            seen.add(node.id)
            node = node.parent
        chain.reverse()
        return Response(chain)

    # ─── Revisions ────────────────────────────────────────────────────
    @action(detail=True, methods=["get"], url_path="revisions")
    def revisions(self, request, pk=None):
        instance = self.get_object()
        page = self.paginate_queryset(instance.revisions.all())
        ser = AuditableEntityRevisionSerializer(page or instance.revisions.all(), many=True)
        if page is not None:
            return self.get_paginated_response(ser.data)
        return Response(ser.data)

    # ─── Operations ───────────────────────────────────────────────────
    @action(detail=True, methods=["post"], url_path="clone")
    def clone(self, request, pk=None):
        src = self.get_object()
        new_name = request.data.get("name") or f"{src.name} (Copy)"
        clone = AuditableEntity.objects.create(
            name=new_name,
            department=src.department,
            department_ref=src.department_ref,
            business_unit=src.business_unit,
            entity_type=src.entity_type,
            primary_owner=src.primary_owner,
            secondary_owner=src.secondary_owner,
            location=src.location,
            audit_frequency=src.audit_frequency,
            primary_language=src.primary_language,
            headcount=src.headcount,
            operating_budget=src.operating_budget,
            estimated_man_days=src.estimated_man_days,
            is_mandatory_to_audit=src.is_mandatory_to_audit,
            cost_center_id="",  # cost centers should not collide
            tags=list(src.tags or []),
            description=src.description,
            inherent_likelihood=src.inherent_likelihood,
            inherent_impact=src.inherent_impact,
            parent=src.parent,
        )
        return Response(
            self.get_serializer(clone).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["get"], url_path="kpis")
    def kpis(self, request):
        """Single-shot KPI strip for the universe dashboard.

        Cached for 60s in Redis to absorb dashboard polling.
        """
        from django.core.cache import cache
        from iams.models import Audit
        cache_key = "audit_universe:kpis:v1"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        active = AuditableEntity.objects.all()
        total = active.count()
        critical = active.filter(risk_rating="Critical").count()
        compliant = active.filter(compliance_status="Compliant").count()
        compliance_rate = round((compliant / total) * 100, 1) if total else 0.0
        open_audits = Audit.objects.exclude(status="Completed").count()
        mandatory = active.filter(is_mandatory_to_audit=True).count()
        mandatory_with_plan = active.filter(
            is_mandatory_to_audit=True, next_audit_date__isnull=False
        ).count()
        plan_progress = (
            round((mandatory_with_plan / mandatory) * 100, 1) if mandatory else 0.0
        )
        payload = {
            "totalEntities": total,
            "criticalRisks": critical,
            "complianceRate": compliance_rate,
            "openAudits": open_audits,
            "planProgress": plan_progress,
            "asOf": timezone.now(),
        }
        cache.set(cache_key, payload, timeout=60)
        return Response(payload)

    @action(detail=False, methods=["get"], url_path="coverage")
    def coverage(self, request):
        """Data-quality report for the audit universe.

        Returns the count for each rule plus the totals needed by the
        Coverage page to render percentages. The matching list endpoints
        live at /api/auditable-entities/ with the corresponding boolean
        filter, so the FE can deep-link from a tile to the offending rows.
        """
        from datetime import timedelta
        three_years_ago = timezone.now().date() - timedelta(days=365 * 3)
        qs = AuditableEntity.objects.all()
        total = qs.count()
        return Response({
            "total": total,
            "withoutOwner": qs.filter(primary_owner__isnull=True).count(),
            "withoutDepartment": qs.filter(department_ref__isnull=True).count(),
            "withoutNextAudit": qs.filter(next_audit_date__isnull=True).count(),
            "neverAudited": qs.filter(last_audit_date__isnull=True).count(),
            "staleOver3Years": qs.filter(last_audit_date__lt=three_years_ago).count(),
            "mandatoryWithoutPlan": qs.filter(
                is_mandatory_to_audit=True, next_audit_date__isnull=True
            ).count(),
            "withoutRiskScore": qs.filter(
                Q(inherent_likelihood__isnull=True) | Q(inherent_impact__isnull=True)
            ).count(),
        })

    # ─── Bulk import / export ─────────────────────────────────────────
    @action(
        detail=False,
        methods=["post"],
        url_path="bulk-import",
        parser_classes=[MultiPartParser, FormParser],
    )
    def bulk_import(self, request):
        """Kick off an async CSV / XLSX import.

        Required form fields:
          ``file``  — the upload (≤25 MB, CSV or XLSX MIME types)
          ``mode``  — ``strict`` or ``lenient`` (default ``lenient``)

        Returns the ``BulkImportJob`` id; poll
        ``/api/audit-universe-import-jobs/{id}/`` for status + per-row errors.
        """
        uploaded = request.FILES.get("file")
        if not uploaded:
            return Response(
                {"detail": "Missing required `file` upload."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Size guard: 25 MB is plenty for ~50k rows of CSV.
        if uploaded.size > 25 * 1024 * 1024:
            return Response(
                {"detail": "Upload exceeds the 25 MB limit."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        name_lower = (uploaded.name or "").lower()
        allowed = name_lower.endswith(".csv") or name_lower.endswith(".xlsx") or name_lower.endswith(".xlsm")
        if not allowed:
            return Response(
                {"detail": "Only .csv and .xlsx uploads are accepted."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        mode = request.data.get("mode") or BulkImportJob.MODE_LENIENT
        if mode not in (BulkImportJob.MODE_STRICT, BulkImportJob.MODE_LENIENT):
            return Response(
                {"detail": "Invalid mode; expected 'strict' or 'lenient'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        job = BulkImportJob.objects.create(
            file=uploaded,
            file_name=uploaded.name or "",
            mode=mode,
            requested_by=request.user if request.user.is_authenticated else None,
            status=BulkImportJob.STATUS_PENDING,
        )

        # Dispatch async; tests run with CELERY_TASK_ALWAYS_EAGER so the
        # job completes inline. In production this hands off to a worker.
        from iams.tasks import process_bulk_import
        process_bulk_import.delay(str(job.id))

        return Response(
            BulkImportJobSerializer(job).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        """Stream the filtered entity list as CSV or XLSX.

        ``?as=csv`` (default) or ``?as=xlsx``. ``as`` is used instead of
        ``format`` because DRF reserves the latter for content
        negotiation and would 404 a value it can't satisfy.
        All standard filters (``status``, ``riskRating``, ``q``, …) apply.
        """
        fmt = (request.query_params.get("as") or "csv").lower()
        qs = self.filter_queryset(self.get_queryset())
        columns = [
            ("id", "id"),
            ("name", "name"),
            ("entity_type", "entityType"),
            ("status", "status"),
            ("risk_rating", "riskRating"),
            ("compliance_status", "complianceStatus"),
            ("audit_frequency", "auditFrequency"),
            ("last_audit_date", "lastAuditDate"),
            ("next_audit_date", "nextAuditDate"),
            ("department", "department"),
            ("cost_center_id", "costCenterId"),
            ("headcount", "headcount"),
            ("operating_budget", "operatingBudget"),
            ("estimated_man_days", "estimatedManDays"),
            ("is_mandatory_to_audit", "isMandatoryToAudit"),
            ("external_source", "external_source"),
            ("external_id", "external_id"),
        ]

        if fmt == "xlsx":
            from openpyxl import Workbook
            from django.http import HttpResponse
            wb = Workbook(write_only=True)
            ws = wb.create_sheet("Audit Universe")
            ws.append([col[1] for col in columns])
            for row in qs.iterator(chunk_size=500):
                ws.append([self._cell(getattr(row, col[0])) for col in columns])
            from io import BytesIO
            buf = BytesIO()
            wb.save(buf)
            buf.seek(0)
            resp = HttpResponse(
                buf.read(),
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
            )
            resp["Content-Disposition"] = (
                'attachment; filename="audit-universe.xlsx"'
            )
            return resp

        # Default: CSV streamed.
        import csv
        from django.http import StreamingHttpResponse

        class Echo:
            def write(self, value):
                return value

        writer = csv.writer(Echo())

        def rows():
            yield writer.writerow([col[1] for col in columns])
            for row in qs.iterator(chunk_size=500):
                yield writer.writerow([self._cell(getattr(row, col[0])) for col in columns])

        resp = StreamingHttpResponse(rows(), content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="audit-universe.csv"'
        return resp

    @staticmethod
    def _cell(value):
        """Coerce a model value into a CSV / XLSX-safe scalar.

        openpyxl's write-only mode only accepts primitive scalars
        (str / int / float / bool / datetime / None) so non-primitives
        like UUID and Decimal get stringified here.
        """
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float, str)):
            return value
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, (list, dict)):
            import json
            return json.dumps(value)
        return str(value)

    @action(detail=False, methods=["post"], url_path="recompute-risk-scores")
    def recompute(self, request):
        """Convenience action that delegates to the risk engine.

        Re-snapshots every entity scored against the active risk model.
        Heavy work happens synchronously here; a future task migrates
        this to a Celery job with a poll-able job id.
        """
        from iams.models import RiskScoringModel
        from iams.risk_engine import recompute_all_scores_for_model

        model = RiskScoringModel.objects.filter(is_active=True).first()
        if model is None:
            return Response(
                {"detail": "No active risk-scoring model is configured."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        count = recompute_all_scores_for_model(model, by_user=request.user)
        return Response({"recomputed": count, "modelId": str(model.id)})

    @action(detail=True, methods=["post"], url_path="reset-risk-overrides")
    def reset_risk_overrides(self, request, pk=None):
        """Clear manual L/I/rating overrides and re-roll from the risks.

        Accepts an optional ``fields`` list (subset of ``likelihood``,
        ``impact``, ``rating``); defaults to all three.
        """
        from iams.risk_rollup import recompute_entity_risk_position

        entity = self.get_object()
        requested = request.data.get("fields") or ["likelihood", "impact", "rating"]
        flag_map = {
            "likelihood": "likelihood_is_overridden",
            "impact": "impact_is_overridden",
            "rating": "risk_rating_is_overridden",
        }
        changed = []
        for key in requested:
            attr = flag_map.get(key)
            if attr and getattr(entity, attr):
                setattr(entity, attr, False)
                changed.append(attr)
        if changed:
            entity.save(update_fields=[*changed, "updated_at"])
        recompute_entity_risk_position(entity)
        entity.refresh_from_db()
        return Response(self.get_serializer(entity).data)


class EntityRiskViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """Discrete risks attached to an auditable entity (engagement).

    Filter the list by ``?entity=<uuid>``. Every create/update/delete
    re-rolls the owning entity's likelihood / impact / risk_rating
    (respecting per-field overrides) via
    ``recompute_entity_risk_position``.
    """

    serializer_class = EntityRiskSerializer
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = EntityRisk.objects.select_related("entity", "owner").all()
        entity_id = self.request.query_params.get("entity")
        if entity_id:
            qs = qs.filter(entity_id=entity_id)
        return qs

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated(), HasPermission("view_audits")()]
        return [IsAuthenticated(), HasPermission("edit_audits")()]

    def _reroll(self, entity):
        from iams.risk_rollup import recompute_entity_risk_position
        recompute_entity_risk_position(entity)

    def perform_create(self, serializer):
        risk = serializer.save()
        self._reroll(risk.entity)

    def perform_update(self, serializer):
        risk = serializer.save()
        self._reroll(risk.entity)

    def perform_destroy(self, instance):
        entity = instance.entity
        instance.delete()
        self._reroll(entity)


class BusinessUnitViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = BusinessUnit.objects.all().select_related("parent", "head").order_by("name", "id")
    serializer_class = BusinessUnitSerializer
    filterset_class = BusinessUnitFilter
    search_fields = ["name", "code", "description"]
    ordering_fields = ["name", "code", "created_at"]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated(), HasPermission("view_audits")()]
        return [IsAuthenticated(), HasPermission("edit_audits")()]


class TagViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = Tag.objects.all().order_by("category", "name")
    serializer_class = TagSerializer
    filterset_class = TagFilter
    search_fields = ["name", "description"]
    ordering_fields = ["name", "category", "created_at"]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated(), HasPermission("view_audits")()]
        return [IsAuthenticated(), HasPermission("edit_audits")()]


class BulkImportJobViewSet(viewsets.ReadOnlyModelViewSet):
    """Poll-only viewset for bulk-import progress.

    Job rows are created by ``POST /api/auditable-entities/bulk-import/``
    and updated by the Celery worker. The FE polls ``retrieve`` while
    ``status`` is in (Pending, Validating, Importing) and stops once it
    transitions to Completed / PartialSuccess / Failed.

    Users only see their own jobs; staff/super-admin see all.
    """

    serializer_class = BulkImportJobSerializer
    permission_classes = [HasPermission("view_audits")]

    def get_queryset(self):
        qs = BulkImportJob.objects.all().select_related("requested_by")
        u = self.request.user
        if getattr(u, "is_superuser", False) or getattr(u, "is_staff", False):
            return qs
        # IAMS uses an in-app super-admin flag on Role (distinct from
        # Django's is_superuser) — surface that here so the global
        # "Audit Universe activity" view stays visible to admins.
        profile = getattr(u, "profile", None)
        if profile and profile.role and profile.role.is_super_admin:
            return qs
        return qs.filter(requested_by=u)


class AuditableEntityRevisionViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only listing of every revision across all entities.

    Per-entity revisions are also exposed via
    ``GET /api/auditable-entities/{id}/revisions/``; this resource
    powers the admin "Audit Universe activity" page.
    """

    queryset = AuditableEntityRevision.objects.all().select_related("entity", "changed_by")
    serializer_class = AuditableEntityRevisionSerializer
    permission_classes = [HasPermission("view_audits")]
    ordering = ["-created_at"]


class RiskHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RiskHistoryEntry.objects.all()
    serializer_class = RiskHistoryEntrySerializer
    permission_classes = [HasPermission("view_audits")]


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """Per-user inbox.

    The list / retrieve / mark-read endpoints are **scoped to the current
    user**. System-wide broadcasts (``recipient=NULL``) are included so
    "from the IAMS team" announcements reach everyone.
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Phase 5 Track 2 — ``select_related("target_content_type")``
        # avoids the N+1 that ``get_targetType`` would otherwise trigger
        # for every notification in a page (the FE bell polls this
        # endpoint at 60s, so the saving compounds).
        qs = Notification.objects.select_related("target_content_type").all()
        user = self.request.user
        if user and user.is_authenticated:
            qs = qs.filter(Q(recipient=user) | Q(recipient__isnull=True))
        # Additional filters (kind, read) — handy for the FE bell badge.
        kind = self.request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        read = self.request.query_params.get("read")
        if read in ("true", "false"):
            qs = qs.filter(read=(read == "true"))
        return qs.order_by("-timestamp")

    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request, pk=None):
        # Honor scoping — users can't mark someone else's row as read.
        item = self.get_object()
        item.read = True
        item.save(update_fields=["read"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="read-all")
    def mark_all_read(self, request):
        self.get_queryset().filter(read=False).update(read=True)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        """Tiny endpoint the FE topbar bell polls every 60 seconds."""
        count = self.get_queryset().filter(read=False).count()
        return Response({"count": count})


class NotificationPreferenceViewSet(viewsets.ModelViewSet):
    """Per-user notification delivery preferences.

    ``list`` returns one row per ``kind`` the user has explicitly set
    plus an in-memory record for every kind they haven't (using the
    defaults from ``iams.notifications.DEFAULT_PREFS``) so the FE can
    render a complete matrix without further lookups.

    ``patch`` upserts a row for a given ``kind``.
    """

    serializer_class = NotificationPreferenceSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None  # tiny set; no need to paginate

    def get_queryset(self):
        return NotificationPreference.objects.filter(user=self.request.user)

    def list(self, request, *args, **kwargs):
        # Merge stored rows with defaults so the FE matrix is always complete.
        from iams.notifications import DEFAULT_PREFS
        stored = {p.kind: p for p in self.get_queryset()}
        merged = []
        for kind, _label in Notification.KIND_CHOICES:
            if kind in stored:
                merged.append(stored[kind])
            else:
                d = DEFAULT_PREFS.get(kind, {"in_app": True, "email": False})
                merged.append(
                    NotificationPreference(
                        user=request.user,
                        kind=kind,
                        in_app_enabled=d["in_app"],
                        email_enabled=d["email"],
                    )
                )
        serializer = self.get_serializer(merged, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        # Upsert semantics: POST to /preferences/ {kind, ...} replaces
        # the row for that kind if it already exists.
        kind = request.data.get("kind")
        if not kind:
            return Response({"detail": "kind is required"}, status=status.HTTP_400_BAD_REQUEST)
        instance = NotificationPreference.objects.filter(user=request.user, kind=kind).first()
        serializer = self.get_serializer(instance, data=request.data, partial=instance is not None)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED if instance is None else status.HTTP_200_OK)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    # Phase 5 Track 2 — ``select_related("target_content_type")`` removes
    # the per-row ContentType lookup that ``get_targetType`` triggers.
    queryset = AuditLogEntry.objects.select_related("target_content_type").all()
    serializer_class = AuditLogEntrySerializer
    permission_classes = [HasPermission("view_reports")]


class FollowUpViewSet(
    AuditedViewSetMixin,
    viewsets.GenericViewSet,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
):
    queryset = FollowUpItem.objects.select_related("finding").all().order_by("due_date", "id")
    serializer_class = FollowUpItemSerializer
    permission_classes = [HasPermission("manage_findings")]


class CommentViewSet(
    AuditedViewSetMixin,
    viewsets.GenericViewSet,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        entity_id = self.request.query_params.get("entity_id")
        if entity_id:
            qs = qs.filter(entity_id=entity_id)
        return qs


class DashboardKPIView(APIView):
    """Top-line KPI cards (FR-DASH-02).

    Now period+department-filterable (FR-DASH-07) and Redis-cached
    (Phase 4 Track 3). Routes through ``iams.dashboards.core_kpis`` so
    the same numbers reach the role bundles below without duplication.

    Query params:
      ?period=YYYY | YYYY-Qn   filter by audit/finding/CAP year/quarter
      ?department=Finance      filter by department name
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from iams.dashboards import _cache_key, cache_or_compute, core_kpis

        period = request.query_params.get("period")
        department = request.query_params.get("department")
        key = _cache_key("kpis", period=period, department=department)
        payload = cache_or_compute(
            key, lambda: core_kpis(period=period, department=department)
        )
        return Response(payload)


class AuditorViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = Auditor.objects.all()
    serializer_class = AuditorSerializer
    permission_classes = [HasPermission("view_audits")]


class AssignmentViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = (
        AuditAssignment.objects.select_related("auditor", "audit")
        .all()
        .order_by("start_date", "id")
    )
    permission_classes = [HasPermission("view_audits")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return AuditAssignmentWriteSerializer
        return AuditAssignmentSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        auditor_id = self.request.query_params.get("auditor_id")
        if auditor_id:
            qs = qs.filter(auditor_id=auditor_id)
        return qs


class TimeEntryViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = TimeEntry.objects.select_related("auditor", "audit").all()
    permission_classes = [HasPermission("view_audits")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return TimeEntryWriteSerializer
        return TimeEntrySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        auditor_id = self.request.query_params.get("auditor_id")
        if auditor_id:
            qs = qs.filter(auditor_id=auditor_id)
        return qs


class HoursBudgetViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = HoursBudget.objects.select_related("audit").all().order_by("id")
    permission_classes = [HasPermission("view_audits")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return HoursBudgetWriteSerializer
        return HoursBudgetSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        audit_id = self.request.query_params.get("audit_id")
        if audit_id:
            qs = qs.filter(audit_id=audit_id)
        return qs


class RiskAssessmentViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = RiskAssessmentRecord.objects.all().order_by("department", "source_row", "id")
    serializer_class = RiskAssessmentRecordSerializer
    permission_classes = [HasPermission("view_audits")]

    def get_queryset(self):
        qs = super().get_queryset()
        department = self.request.query_params.get("department")
        if department:
            qs = qs.filter(department=department)
        return qs


class RiskAssessmentSheetsViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RiskAssessmentSheet.objects.all()
    serializer_class = RiskAssessmentSheetSerializer
    permission_classes = [HasPermission("view_audits")]


class RiskAssessmentMatrixViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RiskAssessmentMatrixCell.objects.all().order_by("likelihood", "impact")
    serializer_class = RiskAssessmentMatrixCellSerializer
    permission_classes = [HasPermission("view_audits")]


class RiskAssessmentSummaryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        RiskAssessmentSummaryItem.objects.select_related("record")
        .all()
        .order_by("record__department", "id")
    )
    serializer_class = RiskAssessmentSummaryItemSerializer
    permission_classes = [HasPermission("view_audits")]


class RiskAssessmentImportIssuesViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RiskAssessmentImportIssue.objects.all().order_by("severity", "id")
    serializer_class = RiskAssessmentImportIssueSerializer
    permission_classes = [HasPermission("manage_settings")]


class ApprovalRequestViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = ApprovalRequest.objects.prefetch_related("steps").all().order_by("-created_at")
    serializer_class = ApprovalRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        # ``?mine=pending`` — requests where the *current* pending step
        # names the calling user (by email or by role). Used by the
        # dashboard "My pending approvals" widget.
        if self.request.query_params.get("mine") == "pending":
            user = self.request.user
            if not (user and user.is_authenticated):
                return qs.none()
            role_name = ""
            profile = getattr(user, "profile", None)
            if profile and profile.role:
                role_name = profile.role.name
            # Subquery: requests whose lowest-order pending step matches user
            qs = qs.filter(
                status="Pending",
                steps__status="Pending",
            ).filter(
                Q(steps__approver__iexact=user.email)
                | Q(steps__role__iexact=role_name)
            ).distinct()
        return qs

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        from iams.workflows import ApprovalError, advance_on_approve, current_step
        obj = self.get_object()
        comment = request.data.get("comments", "")
        # Capture the step before the call (advance_on_approve consumes it)
        step_snapshot = current_step(obj)
        try:
            advance_on_approve(obj, by_user=request.user, comment=comment)
        except ApprovalError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        from iams.audit import record_audit_event
        record_audit_event(
            action=AuditLogEntry.ACTION_APPROVE,
            actor=request.user,
            target=obj,
            details={
                "step_order": step_snapshot.order if step_snapshot else None,
                "step_role": step_snapshot.role if step_snapshot else "",
                "comments": comment,
                "final_status": obj.status,
            },
            request=request,
        )
        obj.refresh_from_db()
        return Response(ApprovalRequestSerializer(obj).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        from iams.workflows import ApprovalError, current_step, reject_request
        obj = self.get_object()
        comment = request.data.get("comments", "")
        step_snapshot = current_step(obj)
        try:
            reject_request(obj, by_user=request.user, comment=comment)
        except ApprovalError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        from iams.audit import record_audit_event
        record_audit_event(
            action=AuditLogEntry.ACTION_REJECT,
            actor=request.user,
            target=obj,
            details={
                "step_order": step_snapshot.order if step_snapshot else None,
                "step_role": step_snapshot.role if step_snapshot else "",
                "comments": comment,
            },
            request=request,
        )
        obj.refresh_from_db()
        return Response(ApprovalRequestSerializer(obj).data)


class WorkProgramViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = WorkProgram.objects.select_related("audit").prefetch_related("procedures__steps").all()
    permission_classes = [HasPermission("view_audits")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return WorkProgramWriteSerializer
        return WorkProgramSerializer


class WorkProcedureViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = WorkProcedure.objects.select_related("work_program").prefetch_related("steps").all()
    permission_classes = [HasPermission("view_audits")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return WorkProcedureWriteSerializer
        return WorkProcedureSerializer


class WorkProcedureStepViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = WorkProcedureStep.objects.select_related("procedure").all()
    serializer_class = WorkProcedureStepSerializer
    permission_classes = [HasPermission("view_audits")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return WorkProcedureStepWriteSerializer
        return WorkProcedureStepSerializer


class AuditReportViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = AuditReport.objects.select_related("audit").prefetch_related("sections").all()
    permission_classes = [HasPermission("view_reports")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return AuditReportWriteSerializer
        return AuditReportSerializer


class AuditReportSectionViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = AuditReportSection.objects.select_related("report").all()
    permission_classes = [HasPermission("view_reports")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return AuditReportSectionWriteSerializer
        return AuditReportSectionSerializer


class ManagedDocumentViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = ManagedDocument.objects.all()
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [HasPermission("view_reports")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return ManagedDocumentWriteSerializer
        return ManagedDocumentSerializer

    def perform_create(self, serializer):
        # Save first so the row exists, then dispatch the AV scan.
        instance = serializer.save()
        if instance.file:
            from iams.tasks import scan_uploaded_file
            scan_uploaded_file.delay(model_label="ManagedDocument", object_id=str(instance.id))

    def perform_update(self, serializer):
        # If the file was replaced, reset scan state and rescan.
        old_file_name = serializer.instance.file.name if serializer.instance.file else None
        instance = serializer.save()
        new_file_name = instance.file.name if instance.file else None
        if new_file_name and new_file_name != old_file_name:
            instance.scan_status = EvidenceFile.SCAN_PENDING
            instance.scan_signature = ""
            instance.quarantined = False
            instance.scanned_at = None
            instance.save(
                update_fields=["scan_status", "scan_signature", "quarantined", "scanned_at"]
            )
            from iams.tasks import scan_uploaded_file
            scan_uploaded_file.delay(model_label="ManagedDocument", object_id=str(instance.id))


class ApprovalChainTemplateViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """Admin-managed approval chain templates.

    Read access requires ``view_audits`` (so the WorkflowApprovals page
    can show "this is the chain that will apply"). Write access requires
    ``manage_settings`` since editing a template changes how every
    future approval is routed.
    """
    queryset = ApprovalChainTemplate.objects.all().order_by("request_type", "name")
    serializer_class = ApprovalChainTemplateSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [HasPermission("view_audits")]
        return [HasPermission("manage_settings")]


class WorkingPaperViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """Engagement-scoped working papers with versioning + sign-off.

    Endpoints:
      GET    /api/working-papers/                       list (filterable by ?audit_id=, ?search=, ?status=)
      GET    /api/working-papers/?currentOnly=true      only the latest version per (audit, reference)
      POST   /api/working-papers/                       create v1 (multipart for file upload)
      PATCH  /api/working-papers/{id}/                  edit draft fields (rejected once signed)
      DELETE /api/working-papers/{id}/                  delete (rejected once signed)
      POST   /api/working-papers/{id}/sign/auditor/     auditor signature
      POST   /api/working-papers/{id}/sign/reviewer/    reviewer signature + lock
      POST   /api/working-papers/{id}/new-version/      create successor (multipart)
      GET    /api/working-papers/{id}/versions/         full chain (oldest → newest)
      GET    /api/working-papers/{id}/download/         signed URL (403 if quarantined, 409 if pending scan)
    """

    queryset = WorkingPaper.objects.select_related("audit", "auditor_signed_by", "reviewer_signed_by").prefetch_related("findings")
    # JSONParser for PATCH-as-JSON edits; Multipart/Form for uploads.
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        if self.action in ("list", "retrieve", "versions", "download"):
            return [HasPermission("view_audits")]
        return [HasPermission("edit_audits")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            from iams.domain_serializers import WorkingPaperWriteSerializer
            return WorkingPaperWriteSerializer
        from iams.domain_serializers import WorkingPaperSerializer
        return WorkingPaperSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        audit_id = self.request.query_params.get("audit_id")
        if audit_id:
            qs = qs.filter(audit_id=audit_id)
        if self.request.query_params.get("currentOnly") == "true":
            qs = qs.filter(is_current_version=True)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(title__icontains=search)
                | Q(description__icontains=search)
                | Q(reference__icontains=search)
                | Q(searchable_text__icontains=search)
            )
        return qs.order_by("audit_id", "reference", "-version")

    def perform_create(self, serializer):
        # Compute file_size_kb from the uploaded file when present so callers
        # don't have to send it explicitly.
        validated = serializer.validated_data
        file_obj = validated.get("file")
        if file_obj is not None and not validated.get("file_size_kb"):
            validated["file_size_kb"] = max(1, file_obj.size // 1024)
        instance = serializer.save()
        from iams.working_papers import populate_searchable_text
        # Populate searchable_text inline (synchronous stub).
        text = populate_searchable_text(instance)
        if text:
            instance.searchable_text = text
            instance.save(update_fields=["searchable_text", "updated_at"])
        if instance.file:
            from iams.tasks import scan_uploaded_file
            scan_uploaded_file.delay(model_label="WorkingPaper", object_id=str(instance.id))

    def perform_update(self, serializer):
        # The model's save() guard handles the actually-signed case;
        # this layer also blocks Under-Review edits to keep the FE crisp.
        if serializer.instance.signed_off_at is not None:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Working paper is signed off; create a new version instead.")
        instance = serializer.save()
        from iams.working_papers import populate_searchable_text
        text = populate_searchable_text(instance)
        if text:
            instance.searchable_text = text
            instance.save(update_fields=["searchable_text", "updated_at"])

    # ── Sign-off actions ─────────────────────────────────────────────
    @action(detail=True, methods=["post"], url_path="sign/auditor")
    def sign_auditor(self, request, pk=None):
        from iams.audit import record_audit_event
        from iams.working_papers import SignOffError, sign_as_auditor
        wp = self.get_object()
        try:
            sign_as_auditor(wp, by_user=request.user)
        except SignOffError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit_event(
            action=AuditLogEntry.ACTION_OTHER,
            actor=request.user,
            target=wp,
            details={"event": "working_paper_auditor_signed"},
            request=request,
        )
        from iams.domain_serializers import WorkingPaperSerializer
        return Response(WorkingPaperSerializer(wp).data)

    @action(detail=True, methods=["post"], url_path="sign/reviewer")
    def sign_reviewer(self, request, pk=None):
        from iams.audit import record_audit_event
        from iams.working_papers import SignOffError, sign_as_reviewer
        wp = self.get_object()
        try:
            sign_as_reviewer(wp, by_user=request.user)
        except SignOffError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit_event(
            action=AuditLogEntry.ACTION_OTHER,
            actor=request.user,
            target=wp,
            details={"event": "working_paper_reviewer_signed", "finalized": True},
            request=request,
        )
        from iams.domain_serializers import WorkingPaperSerializer
        return Response(WorkingPaperSerializer(wp).data)

    # ── Versioning ──────────────────────────────────────────────────
    @action(detail=True, methods=["post"], url_path="new-version")
    def new_version(self, request, pk=None):
        from iams.audit import record_audit_event
        from iams.working_papers import create_new_version
        parent = self.get_object()
        file_obj = request.FILES.get("file")
        new_wp = create_new_version(
            parent,
            file=file_obj,
            title=request.data.get("title"),
            description=request.data.get("description"),
        )
        if file_obj is not None:
            new_wp.file_size_kb = max(1, file_obj.size // 1024)
            new_wp.save(update_fields=["file_size_kb", "updated_at"])
            from iams.tasks import scan_uploaded_file
            scan_uploaded_file.delay(model_label="WorkingPaper", object_id=str(new_wp.id))
        record_audit_event(
            action=AuditLogEntry.ACTION_OTHER,
            actor=request.user,
            target=new_wp,
            details={"event": "working_paper_new_version", "parent_id": str(parent.id), "version": new_wp.version},
            request=request,
        )
        from iams.domain_serializers import WorkingPaperSerializer
        return Response(WorkingPaperSerializer(new_wp).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="versions")
    def versions(self, request, pk=None):
        """Full version chain (oldest → newest) for the same (audit, reference)."""
        wp = self.get_object()
        chain = WorkingPaper.objects.filter(
            audit_id=wp.audit_id, reference=wp.reference,
        ).order_by("version")
        from iams.domain_serializers import WorkingPaperSerializer
        serializer = WorkingPaperSerializer(chain, many=True)
        return Response(serializer.data)

    # ── Download (mirrors EvidenceFileViewSet.download) ─────────────
    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        wp = self.get_object()
        if wp.quarantined:
            return Response(
                {
                    "detail": "File is quarantined.",
                    "scanStatus": wp.scan_status,
                    "scanSignature": wp.scan_signature,
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        if wp.scan_status == EvidenceFile.SCAN_PENDING:
            return Response(
                {"detail": "File is still being scanned.", "scanStatus": wp.scan_status},
                status=status.HTTP_409_CONFLICT,
            )
        if not wp.file:
            return Response({"detail": "No file available."}, status=status.HTTP_404_NOT_FOUND)
        url = wp.file.url
        if not url.startswith(("http://", "https://")):
            url = request.build_absolute_uri(url)
        return Response({"url": url})


# ═════════════════════════════════════════════════════════════════════
# Phase 3 Track 2 — QAIP viewsets + dashboard
# ═════════════════════════════════════════════════════════════════════
from iams.models import AuditKPI, QAIPAssessment, QAIPFinding, StakeholderSurvey  # noqa: E402
from iams.domain_serializers import (  # noqa: E402
    AuditKPISerializer,
    QAIPAssessmentSerializer,
    QAIPFindingSerializer,
    StakeholderSurveySerializer,
)


class QAIPAssessmentViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = (
        QAIPAssessment.objects
        .select_related("lead_reviewer")
        .prefetch_related("findings")
        .all()
    )
    serializer_class = QAIPAssessmentSerializer
    permission_classes = [HasPermission("view_reports")]

    def get_queryset(self):
        qs = super().get_queryset()
        type_filter = self.request.query_params.get("type")
        if type_filter:
            qs = qs.filter(type=type_filter)
        period = self.request.query_params.get("period")
        if period:
            qs = qs.filter(period=period)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class QAIPFindingViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = QAIPFinding.objects.select_related("assessment", "owner_ref").all()
    serializer_class = QAIPFindingSerializer
    permission_classes = [HasPermission("view_reports")]

    def get_queryset(self):
        qs = super().get_queryset()
        assessment_id = self.request.query_params.get("assessment_id")
        if assessment_id:
            qs = qs.filter(assessment_id=assessment_id)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class StakeholderSurveyViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = StakeholderSurvey.objects.select_related("audit", "respondent").all()
    serializer_class = StakeholderSurveySerializer
    permission_classes = [HasPermission("view_reports")]

    def get_queryset(self):
        qs = super().get_queryset()
        audit_id = self.request.query_params.get("audit_id")
        if audit_id:
            qs = qs.filter(audit_id=audit_id)
        role = self.request.query_params.get("respondent_role")
        if role:
            qs = qs.filter(respondent_role=role)
        return qs


class AuditKPIViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = AuditKPI.objects.all()
    serializer_class = AuditKPISerializer
    permission_classes = [HasPermission("view_reports")]

    def get_queryset(self):
        qs = super().get_queryset()
        kpi_type = self.request.query_params.get("kpi_type")
        if kpi_type:
            qs = qs.filter(kpi_type=kpi_type)
        period = self.request.query_params.get("period")
        if period:
            qs = qs.filter(period=period)
        return qs


class QAIPDashboardView(APIView):
    """Aggregated QAIP overview for the dashboard / annual report.

    Returns a single payload with:
      - assessmentsByType: counts of assessments grouped by type
      - assessmentsByStatus: counts grouped by status
      - openQaipFindings / criticalQaipFindings: rollup counts
      - avgSatisfaction: across all surveys (optional period filter)
      - kpis: list of {kpiType, target, actual, variance, favorable}
              for the requested period (defaults to most recent period
              present in the table)

    Query params:
      - ?period=PERIOD   restrict aggregations to that period label
    """

    permission_classes = [HasPermission("view_reports")]

    def get(self, request):
        from django.db.models import Avg
        period = request.query_params.get("period")

        # Assessments rollups
        assessment_qs = QAIPAssessment.objects.all()
        if period:
            assessment_qs = assessment_qs.filter(period=period)

        by_type = list(
            assessment_qs.values("type").annotate(count=Count("id")).order_by("type")
        )
        by_status = list(
            assessment_qs.values("status").annotate(count=Count("id")).order_by("status")
        )

        # Findings rollups (open + critical)
        finding_qs = QAIPFinding.objects.all()
        if period:
            finding_qs = finding_qs.filter(assessment__period=period)
        open_findings = finding_qs.exclude(status="closed").count()
        critical_findings = finding_qs.filter(rating="critical").count()

        # Avg satisfaction
        survey_qs = StakeholderSurvey.objects.all()
        if period:
            # ``StakeholderSurvey`` doesn't have its own period field; we
            # interpret period filter as a year and match against
            # ``submitted_at__year`` when it's a 4-digit string.
            if period.isdigit() and len(period) == 4:
                survey_qs = survey_qs.filter(submitted_at__year=int(period))
        avg_score = survey_qs.aggregate(avg=Avg("satisfaction_score"))["avg"]

        # KPIs
        kpi_qs = AuditKPI.objects.all()
        if period:
            kpi_qs = kpi_qs.filter(period=period)
        else:
            latest_period = (
                AuditKPI.objects.order_by("-period").values_list("period", flat=True).first()
            )
            if latest_period:
                kpi_qs = kpi_qs.filter(period=latest_period)
        kpi_payload = AuditKPISerializer(kpi_qs.order_by("kpi_type"), many=True).data

        return Response({
            "period": period,
            "assessmentsByType": by_type,
            "assessmentsByStatus": by_status,
            "openQaipFindings": open_findings,
            "criticalQaipFindings": critical_findings,
            "avgSatisfaction": float(avg_score) if avg_score is not None else None,
            "surveyResponseCount": survey_qs.count(),
            "kpis": kpi_payload,
        })


# ═════════════════════════════════════════════════════════════════════
# Phase 3 Track 3 — CSA viewsets
# ═════════════════════════════════════════════════════════════════════
from iams.models import CSAAnswer, CSAQuestion, CSAQuestionnaire, CSAResponse  # noqa: E402
from iams.domain_serializers import (  # noqa: E402
    CSAAnswerSerializer,
    CSAQuestionSerializer,
    CSAQuestionnaireSerializer,
    CSAResponseSerializer,
)


class CSAQuestionnaireViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """Questionnaire CRUD.

    Read access requires ``view_audits`` (auditees need to see the
    questionnaire before responding). Write requires ``manage_settings``
    since publishing a questionnaire decides what every business unit
    answers against.
    """
    queryset = CSAQuestionnaire.objects.prefetch_related("questions").all()
    serializer_class = CSAQuestionnaireSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [HasPermission("view_audits")]
        return [HasPermission("manage_settings")]

    def get_queryset(self):
        qs = super().get_queryset()
        framework = self.request.query_params.get("framework")
        if framework:
            qs = qs.filter(framework=framework)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class CSAQuestionViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = CSAQuestion.objects.select_related("questionnaire").all()
    serializer_class = CSAQuestionSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [HasPermission("view_audits")]
        return [HasPermission("manage_settings")]

    def get_queryset(self):
        qs = super().get_queryset()
        questionnaire_id = self.request.query_params.get("questionnaire_id")
        if questionnaire_id:
            qs = qs.filter(questionnaire_id=questionnaire_id)
        return qs


class CSAResponseViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """Response CRUD + submit/close actions.

    Any authenticated user can list/view their own responses (or all,
    when they have ``view_audits``); creating a response is open to
    authenticated users (business-unit owners self-serve). Submit and
    close are domain actions with their own auth checks in the service
    layer.
    """
    queryset = (
        CSAResponse.objects
        .select_related("questionnaire", "entity", "responder")
        .prefetch_related("answers", "answers__question")
        .all()
    )
    serializer_class = CSAResponseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        questionnaire_id = self.request.query_params.get("questionnaire_id")
        if questionnaire_id:
            qs = qs.filter(questionnaire_id=questionnaire_id)
        entity_id = self.request.query_params.get("entity_id")
        if entity_id:
            qs = qs.filter(entity_id=entity_id)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        if self.request.query_params.get("weak") == "true":
            qs = qs.filter(is_weak=True)
        return qs

    def perform_create(self, serializer):
        # Auto-stamp the responder as the calling user unless they're an
        # auditor creating on someone else's behalf.
        instance = serializer.save()
        if instance.responder_id is None:
            instance.responder = self.request.user
            instance.save(update_fields=["responder", "updated_at"])

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        from iams.audit import record_audit_event
        from iams.csa import CSAError, submit_response
        response = self.get_object()
        try:
            submit_response(response, by_user=request.user)
        except CSAError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit_event(
            action=AuditLogEntry.ACTION_OTHER,
            actor=request.user,
            target=response,
            details={
                "event": "csa_response_submitted",
                "score_overall": str(response.score_overall),
                "is_weak": response.is_weak,
            },
            request=request,
        )
        response.refresh_from_db()
        return Response(CSAResponseSerializer(response).data)

    @action(detail=True, methods=["post"], url_path="close")
    def close(self, request, pk=None):
        from iams.audit import record_audit_event
        from iams.csa import CSAError, close_response
        response = self.get_object()
        try:
            close_response(response, by_user=request.user)
        except CSAError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit_event(
            action=AuditLogEntry.ACTION_OTHER,
            actor=request.user,
            target=response,
            details={"event": "csa_response_closed"},
            request=request,
        )
        return Response(CSAResponseSerializer(response).data)


class CSAAnswerViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = CSAAnswer.objects.select_related("response", "question", "evidence_file").all()
    serializer_class = CSAAnswerSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        response_id = self.request.query_params.get("response_id")
        if response_id:
            qs = qs.filter(response_id=response_id)
        return qs

    @action(detail=True, methods=["post"], url_path="challenge")
    def challenge(self, request, pk=None):
        """Auditor opens a challenge on this answer. Body: ``{"note": "..."}``."""
        from iams.audit import record_audit_event
        from iams.csa import CSAError, open_challenge
        answer = self.get_object()
        note = (request.data.get("note") or "").strip()
        try:
            open_challenge(answer, by_user=request.user, note=note)
        except CSAError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit_event(
            action=AuditLogEntry.ACTION_OTHER,
            actor=request.user,
            target=answer.response,
            details={"event": "csa_answer_challenged", "answer_id": str(answer.id), "note": note},
            request=request,
        )
        return Response(CSAAnswerSerializer(answer).data)

    @action(detail=True, methods=["post"], url_path="resolve")
    def resolve(self, request, pk=None):
        """Resolve a pending challenge. Body: ``{"note": "..."}``."""
        from iams.audit import record_audit_event
        from iams.csa import CSAError, resolve_challenge
        answer = self.get_object()
        note = (request.data.get("note") or "").strip()
        try:
            resolve_challenge(answer, by_user=request.user, note=note)
        except CSAError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit_event(
            action=AuditLogEntry.ACTION_OTHER,
            actor=request.user,
            target=answer.response,
            details={"event": "csa_answer_resolved", "answer_id": str(answer.id)},
            request=request,
        )
        return Response(CSAAnswerSerializer(answer).data)


# ═════════════════════════════════════════════════════════════════════
# Phase 3 Track 4 — ICFR viewsets
# ═════════════════════════════════════════════════════════════════════
from iams.models import (  # noqa: E402
    Control,
    ControlException,
    ControlTest,
    DeficiencyReport,
)
from iams.domain_serializers import (  # noqa: E402
    ControlExceptionSerializer,
    ControlSerializer,
    ControlTestSerializer,
    DeficiencyReportSerializer,
)


class ControlViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = Control.objects.select_related("entity", "owner_ref").all()
    serializer_class = ControlSerializer
    permission_classes = [HasPermission("view_audits")]

    def get_queryset(self):
        qs = super().get_queryset()
        framework = self.request.query_params.get("framework")
        if framework:
            qs = qs.filter(framework=framework)
        entity_id = self.request.query_params.get("entity_id")
        if entity_id:
            qs = qs.filter(entity_id=entity_id)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class ControlTestViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = (
        ControlTest.objects
        .select_related("control", "control__entity", "tester", "reviewer")
        .prefetch_related("exceptions", "deficiency")
        .all()
    )
    serializer_class = ControlTestSerializer
    permission_classes = [HasPermission("view_audits")]

    def get_queryset(self):
        qs = super().get_queryset()
        control_id = self.request.query_params.get("control_id")
        if control_id:
            qs = qs.filter(control_id=control_id)
        period = self.request.query_params.get("period")
        if period:
            qs = qs.filter(period=period)
        test_type = self.request.query_params.get("test_type")
        if test_type:
            qs = qs.filter(test_type=test_type)
        return qs

    @action(detail=True, methods=["post"], url_path="record-result")
    def record_result(self, request, pk=None):
        """Record a management or auditor conclusion on this test.

        Body::

            {"role": "auditor"|"management",
             "conclusion": "effective"|"deficient"|"not_tested",
             "notes": "…"}

        Returns the updated test. A ``deficient`` auditor conclusion
        auto-creates a draft DeficiencyReport.
        """
        from iams.audit import record_audit_event
        from iams.icfr import ICFRError, record_test_result
        test = self.get_object()
        try:
            record_test_result(
                test,
                by_user=request.user,
                role=(request.data.get("role") or ""),
                conclusion=(request.data.get("conclusion") or ""),
                notes=(request.data.get("notes") or ""),
            )
        except ICFRError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit_event(
            action=AuditLogEntry.ACTION_OTHER,
            actor=request.user,
            target=test,
            details={
                "event": "icfr_test_result_recorded",
                "role": request.data.get("role"),
                "conclusion": request.data.get("conclusion"),
            },
            request=request,
        )
        test.refresh_from_db()
        return Response(ControlTestSerializer(test).data)


class ControlExceptionViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = ControlException.objects.select_related("test").prefetch_related("evidence_files").all()
    serializer_class = ControlExceptionSerializer
    permission_classes = [HasPermission("view_audits")]

    def get_queryset(self):
        qs = super().get_queryset()
        test_id = self.request.query_params.get("test_id")
        if test_id:
            qs = qs.filter(test_id=test_id)
        severity = self.request.query_params.get("severity")
        if severity:
            qs = qs.filter(severity=severity)
        return qs


class DeficiencyReportViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = DeficiencyReport.objects.select_related("test", "test__control").all()
    serializer_class = DeficiencyReportSerializer
    permission_classes = [HasPermission("view_audits")]

    def get_queryset(self):
        qs = super().get_queryset()
        classification = self.request.query_params.get("classification")
        if classification:
            qs = qs.filter(classification=classification)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @action(detail=True, methods=["post"], url_path="open")
    def open_action(self, request, pk=None):
        from iams.audit import record_audit_event
        from iams.icfr import ICFRError, open_deficiency
        deficiency = self.get_object()
        try:
            open_deficiency(
                deficiency,
                by_user=request.user,
                classification=(request.data.get("classification") or ""),
                narrative=(request.data.get("narrative") or ""),
                recommendation=(request.data.get("recommendation") or ""),
                target_resolution_date=request.data.get("targetResolutionDate"),
                owner=(request.data.get("owner") or ""),
            )
        except ICFRError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit_event(
            action=AuditLogEntry.ACTION_OTHER,
            actor=request.user,
            target=deficiency.test,
            details={"event": "icfr_deficiency_opened", "classification": deficiency.classification},
            request=request,
        )
        return Response(DeficiencyReportSerializer(deficiency).data)

    @action(detail=True, methods=["post"], url_path="close")
    def close_action(self, request, pk=None):
        from iams.audit import record_audit_event
        from iams.icfr import ICFRError, close_deficiency
        deficiency = self.get_object()
        try:
            close_deficiency(
                deficiency,
                by_user=request.user,
                management_response=(request.data.get("managementResponse") or ""),
            )
        except ICFRError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit_event(
            action=AuditLogEntry.ACTION_OTHER,
            actor=request.user,
            target=deficiency.test,
            details={"event": "icfr_deficiency_closed"},
            request=request,
        )
        return Response(DeficiencyReportSerializer(deficiency).data)


class ICFRSummaryView(APIView):
    """ICFR summary for FE dashboard + Phase 4 PDF export.

    Query params:
      - ?period=PERIOD   restrict test/exception/deficiency counts to that period
    """
    permission_classes = [HasPermission("view_audits")]

    def get(self, request):
        from iams.icfr import build_icfr_summary
        payload = build_icfr_summary(period=request.query_params.get("period"))
        return Response(payload)


# ═════════════════════════════════════════════════════════════════════
# Phase 4 Track 1 — Risk Engine viewsets
# ═════════════════════════════════════════════════════════════════════
from iams.models import (  # noqa: E402
    EntityRiskScore,
    RiskFactor,
    RiskFactorWeight,
    RiskScoringModel,
)
from iams.domain_serializers import (  # noqa: E402
    EntityRiskScoreSerializer,
    RiskFactorSerializer,
    RiskFactorWeightSerializer,
    RiskScoringModelSerializer,
)


class RiskFactorViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = RiskFactor.objects.all().order_by("name")
    serializer_class = RiskFactorSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [HasPermission("view_audits")]
        return [HasPermission("manage_settings")]


class RiskScoringModelViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = RiskScoringModel.objects.prefetch_related("factor_weights__factor").all().order_by("name", "-version")
    serializer_class = RiskScoringModelSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [HasPermission("view_audits")]
        return [HasPermission("manage_settings")]

    @action(detail=True, methods=["post"], url_path="recompute")
    def recompute(self, request, pk=None):
        """Re-snapshot every entity's current score for this model.

        Useful after editing factor weights / formula. Returns the
        number of rows re-snapshotted.
        """
        from iams.audit import record_audit_event
        from iams.risk_engine import recompute_all_scores_for_model
        model = self.get_object()
        n = recompute_all_scores_for_model(model, by_user=request.user)
        record_audit_event(
            action=AuditLogEntry.ACTION_OTHER,
            actor=request.user,
            target=model,
            details={"event": "risk_model_bulk_recompute", "rows": n},
            request=request,
        )
        return Response({"recomputed": n})


class RiskFactorWeightViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """Per-model factor weights, attached via the through-model."""
    queryset = RiskFactorWeight.objects.select_related("factor", "scoring_model").all()
    serializer_class = RiskFactorWeightSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [HasPermission("view_audits")]
        return [HasPermission("manage_settings")]

    def get_queryset(self):
        qs = super().get_queryset()
        model_id = self.request.query_params.get("scoring_model_id")
        if model_id:
            qs = qs.filter(scoring_model_id=model_id)
        return qs

    def perform_create(self, serializer):
        # ``scoring_model`` is path-supplied via the query param when nested,
        # or in the body when called flat. We allow both.
        scoring_model_id = self.request.data.get("scoring_model_id") or self.request.query_params.get("scoring_model_id")
        if not scoring_model_id:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"scoring_model_id": "required"})
        serializer.save(scoring_model_id=scoring_model_id)


class EntityRiskScoreViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """Read-mostly endpoint over the score history.

    Writes go through the ``record`` custom action which routes
    ``factor_values`` through the engine so the composite is always
    consistent with the formula. Direct POSTs to this endpoint are
    blocked.
    """
    queryset = (
        EntityRiskScore.objects
        .select_related("entity", "scoring_model", "snapshot_by")
        .all()
    )
    serializer_class = EntityRiskScoreSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [HasPermission("view_audits")]
        return [HasPermission("manage_settings")]

    def create(self, request, *args, **kwargs):
        return Response(
            {"detail": "Use POST /api/risk/scores/record/ instead."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def update(self, request, *args, **kwargs):
        return Response(
            {"detail": "EntityRiskScore is append-only; create a new snapshot via /record/."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        return Response(
            {"detail": "EntityRiskScore is append-only; cannot delete history."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def get_queryset(self):
        qs = super().get_queryset()
        entity_id = self.request.query_params.get("entity_id")
        if entity_id:
            qs = qs.filter(entity_id=entity_id)
        model_id = self.request.query_params.get("scoring_model_id")
        if model_id:
            qs = qs.filter(scoring_model_id=model_id)
        if self.request.query_params.get("currentOnly") == "true":
            qs = qs.filter(is_current=True)
        if self.request.query_params.get("highRiskOnly") == "true":
            qs = qs.filter(is_high_risk=True, is_current=True)
        return qs.order_by("-snapshot_at")

    @action(detail=False, methods=["post"], url_path="record")
    def record(self, request):
        """Record a new score snapshot for an entity.

        Body::

            {"entityId": "...", "scoringModelId": "...",
             "factorValues": {"impact": 4, "likelihood": 3, ...},
             "notes": "Quarterly refresh"}
        """
        from iams.audit import record_audit_event
        from iams.risk_engine import RiskEngineError, record_score

        entity_id = request.data.get("entityId")
        model_id = request.data.get("scoringModelId")
        factor_values = request.data.get("factorValues") or {}
        notes = request.data.get("notes") or ""
        if not entity_id or not model_id:
            return Response(
                {"detail": "entityId and scoringModelId are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            entity = AuditableEntity.objects.get(pk=entity_id)
            model = RiskScoringModel.objects.get(pk=model_id)
        except (AuditableEntity.DoesNotExist, RiskScoringModel.DoesNotExist):
            return Response({"detail": "entity or scoring model not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            score = record_score(
                entity, model=model, factor_values=factor_values,
                by_user=request.user, notes=notes,
            )
        except RiskEngineError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        record_audit_event(
            action=AuditLogEntry.ACTION_OTHER,
            actor=request.user,
            target=score,
            details={
                "event": "risk_score_recorded",
                "entity_id": str(entity.id),
                "model_id": str(model.id),
                "composite_score": str(score.composite_score),
                "is_high_risk": score.is_high_risk,
            },
            request=request,
        )
        return Response(EntityRiskScoreSerializer(score).data, status=status.HTTP_201_CREATED)


class RiskHeatMapView(APIView):
    """Returns the likelihood × impact bucket grid for a scoring model.

    Query params:
      ?scoring_model_id=...   (required)
    """
    permission_classes = [HasPermission("view_audits")]

    def get(self, request):
        from iams.risk_engine import RiskEngineError, heat_map
        model_id = request.query_params.get("scoring_model_id")
        if not model_id:
            return Response(
                {"detail": "scoring_model_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            model = RiskScoringModel.objects.get(pk=model_id)
        except RiskScoringModel.DoesNotExist:
            return Response({"detail": "scoring model not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            payload = heat_map(model)
        except RiskEngineError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload)


class GenerateAuditPlanView(APIView):
    """Generate a draft Annual Audit Plan from the top-N entities by risk.

    Body::

        {"scoringModelId": "...", "year": 2026, "topN": 20}

    Returns the created ``ApprovalRequest`` (chain auto-applied).
    """
    permission_classes = [HasPermission("create_audits")]

    def post(self, request):
        from iams.audit import record_audit_event
        from iams.risk_engine import RiskEngineError, generate_audit_plan_draft

        model_id = request.data.get("scoringModelId")
        year = request.data.get("year")
        top_n = int(request.data.get("topN") or 20)
        if not model_id or not year:
            return Response(
                {"detail": "scoringModelId and year are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            model = RiskScoringModel.objects.get(pk=model_id)
        except RiskScoringModel.DoesNotExist:
            return Response({"detail": "scoring model not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            req = generate_audit_plan_draft(
                model=model, year=int(year), top_n=top_n,
                requested_by=request.user,
            )
        except RiskEngineError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        record_audit_event(
            action=AuditLogEntry.ACTION_OTHER,
            actor=request.user,
            target=req,
            details={
                "event": "audit_plan_generated_from_risk",
                "year": int(year),
                "top_n": top_n,
                "scoring_model": model.name,
            },
            request=request,
        )
        return Response(ApprovalRequestSerializer(req).data, status=status.HTTP_201_CREATED)


# ═════════════════════════════════════════════════════════════════════
# Phase 4 Track 2 — Report Generation viewset
# ═════════════════════════════════════════════════════════════════════
from iams.models import ReportJob  # noqa: E402
from iams.domain_serializers import ReportJobSerializer  # noqa: E402


class ReportJobViewSet(viewsets.ReadOnlyModelViewSet):
    """List / inspect / download report jobs.

    Job creation goes through ``POST /api/reports/generate/`` so the
    Celery dispatch logic lives in one place. The viewset is otherwise
    read-only — jobs cannot be edited or deleted via the API (they
    expire via a retention task in Phase 5).
    """
    serializer_class = ReportJobSerializer
    permission_classes = [HasPermission("view_reports")]

    def get_queryset(self):
        qs = ReportJob.objects.select_related("requested_by").all().order_by("-created_at")
        # Users see their own jobs by default. ``manage_settings`` users
        # see the whole org.
        user = self.request.user
        profile = getattr(user, "profile", None)
        role = profile.role if profile else None
        is_admin = bool(role and (role.is_super_admin or role.permissions.filter(key="manage_settings").exists()))
        if not is_admin:
            qs = qs.filter(requested_by=user)
        # Filters
        kind = self.request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        """Return a download URL for the rendered file.

        Refuses with 409 while the job is still pending/running,
        with 404 when the job failed (no file), and otherwise issues
        a signed URL (MinIO) or absolute media URL (dev).
        """
        job = self.get_object()
        if job.status == ReportJob.STATUS_PENDING or job.status == ReportJob.STATUS_RUNNING:
            return Response(
                {"detail": "Report is still being generated.", "status": job.status},
                status=status.HTTP_409_CONFLICT,
            )
        if job.status != ReportJob.STATUS_COMPLETED or not job.output_file:
            return Response(
                {"detail": "Report file unavailable.", "status": job.status, "error": job.error},
                status=status.HTTP_404_NOT_FOUND,
            )
        url = job.output_file.url
        if not url.startswith(("http://", "https://")):
            url = request.build_absolute_uri(url)
        return Response({"url": url, "fileSizeKb": job.file_size_kb})


class GenerateReportView(APIView):
    """Create a ReportJob + enqueue the Celery task.

    Body::

        {"kind": "audit_summary"|...,
         "title": "Optional human label",
         "parameters": {"audit_id": "..."}}

    Returns the created ReportJob (status='pending'). The FE then polls
    ``GET /api/reports/jobs/{id}/`` for status, or relies on the
    in-app notification dispatched when the task finishes.
    """
    permission_classes = [HasPermission("view_reports")]

    def post(self, request):
        from iams.audit import record_audit_event
        from iams.reports import RENDERERS

        kind = request.data.get("kind")
        title = request.data.get("title") or ""
        parameters = request.data.get("parameters") or {}
        if not kind:
            return Response({"detail": "kind is required."}, status=status.HTTP_400_BAD_REQUEST)
        renderer_cls = RENDERERS.get(kind)
        if renderer_cls is None:
            return Response(
                {"detail": f"Unknown report kind '{kind}'.",
                 "supportedKinds": sorted(RENDERERS.keys())},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ``export_reports`` permission required for Excel exports
        # (organizationally these tend to leave the system); PDFs only
        # need ``view_reports``.
        output_format = renderer_cls.output_format
        if output_format == ReportJob.FORMAT_XLSX:
            if not HasPermission("export_reports").has_permission(request, self):
                return Response(
                    {"detail": "export_reports permission required for Excel exports."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        job = ReportJob.objects.create(
            kind=kind, title=title or renderer_cls().kind,
            parameters=parameters,
            output_format=output_format,
            requested_by=request.user,
            status=ReportJob.STATUS_PENDING,
        )
        # Enqueue. Test settings run eagerly; prod is async via Celery.
        from iams.tasks import generate_report
        generate_report.delay(str(job.pk))

        record_audit_event(
            action=AuditLogEntry.ACTION_EXPORT,
            actor=request.user,
            target=job,
            details={"event": "report_job_created", "kind": kind, "params": parameters},
            request=request,
        )
        job.refresh_from_db()
        return Response(ReportJobSerializer(job).data, status=status.HTTP_201_CREATED)


# ═════════════════════════════════════════════════════════════════════
# Phase 4 Track 3 — Dashboard endpoints
# ═════════════════════════════════════════════════════════════════════
from iams.dashboards import (  # noqa: E402
    VALID_ROLES,
    _cache_key,
    cache_or_compute,
    core_kpis,
    rating_summary,
    recent_activity,
    risk_heatmap_by_department,
    role_bundle,
    trends,
    upcoming_audits,
)


class DashboardTrendsView(APIView):
    """Year-over-year quarterly trends (FR-DASH-10).

    Query params: ?period=YoY|FY2026 (default YoY) &department=Finance
    """
    permission_classes = [HasPermission("view_reports")]

    def get(self, request):
        period = request.query_params.get("period") or "YoY"
        department = request.query_params.get("department")
        key = _cache_key("trends", period=period, department=department)
        payload = cache_or_compute(
            key, lambda: trends(period=period, department=department)
        )
        return Response(payload)


class DashboardRiskHeatmapByDepartmentView(APIView):
    """Department × risk-category aggregate of current EntityRiskScore rows."""
    permission_classes = [HasPermission("view_reports")]

    def get(self, request):
        key = _cache_key("risk-heatmap")
        payload = cache_or_compute(key, risk_heatmap_by_department)
        return Response(payload)


class DashboardRatingSummaryView(APIView):
    """Rating rollups across QAIP / ICFR / CSA (FR-DASH-09)."""
    permission_classes = [HasPermission("view_reports")]

    def get(self, request):
        period = request.query_params.get("period")
        key = _cache_key("ratings", period=period)
        payload = cache_or_compute(key, lambda: rating_summary(period=period))
        return Response(payload)


class DashboardActivityView(APIView):
    """Recent activity feed (FR-DASH-05)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit = min(int(request.query_params.get("limit", 20)), 100)
        # Don't cache — should be live
        return Response(recent_activity(limit=limit))


class DashboardUpcomingAuditsView(APIView):
    """Upcoming audits (FR-DASH-06)."""
    permission_classes = [HasPermission("view_audits")]

    def get(self, request):
        limit = min(int(request.query_params.get("limit", 10)), 50)
        department = request.query_params.get("department")
        key = _cache_key("upcoming", limit=limit, department=department)
        payload = cache_or_compute(
            key, lambda: upcoming_audits(limit=limit, department=department)
        )
        return Response(payload)


class DashboardRoleView(APIView):
    """Role-specific pre-composed dashboard bundles.

    Path: /api/dashboard/role/<role>/
    Roles: executive / manager / auditor / auditee
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, role):
        role = (role or "").lower()
        if role not in VALID_ROLES:
            return Response(
                {"detail": f"role must be one of {sorted(VALID_ROLES)}",
                 "supported": sorted(VALID_ROLES)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user_email = getattr(request.user, "email", None)
        # Cache key includes user_email for auditor / auditee bundles
        # because those slice by ownership.
        key = _cache_key("role", role=role, user_email=user_email)
        payload = cache_or_compute(
            key, lambda: role_bundle(role=role, user_email=user_email)
        )
        return Response(payload)
