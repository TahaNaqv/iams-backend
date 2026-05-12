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
    AuditableEntitySerializer,
    AuditorSerializer,
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
    Auditor,
    ChecklistItem,
    Comment,
    CorrectiveAction,
    Department,
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


class DepartmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [HasPermission("view_audits")]


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


class AuditableEntityViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditableEntity.objects.all().order_by("name", "id")
    serializer_class = AuditableEntitySerializer
    permission_classes = [HasPermission("view_audits")]


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
        qs = Notification.objects.all()
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
    queryset = AuditLogEntry.objects.all()
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
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.now().date()
        open_audits = Audit.objects.exclude(status="Completed").count()
        overdue_findings = Finding.objects.filter(~Q(status="Closed"), due_date__lt=today).count()
        pending_caps = CorrectiveAction.objects.exclude(status="Closed").count()
        total_caps = CorrectiveAction.objects.count()
        closed_caps = CorrectiveAction.objects.filter(status="Closed").count()
        completion_rate = int((closed_caps / total_caps) * 100) if total_caps else 0
        return Response(
            {
                "openAudits": open_audits,
                "overdueFindings": overdue_findings,
                "pendingCAPs": pending_caps,
                "completionRate": completion_rate,
            }
        )


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
