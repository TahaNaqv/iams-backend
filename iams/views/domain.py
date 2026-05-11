from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser

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
    Notification,
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
    TimeEntry,
    TimelineEvent,
)
from iams.permissions import HasPermission


class AuditViewSet(viewsets.ModelViewSet):
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


class FindingViewSet(viewsets.ModelViewSet):
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


class CorrectiveActionViewSet(viewsets.ModelViewSet):
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


class ChecklistItemViewSet(viewsets.ModelViewSet):
    queryset = ChecklistItem.objects.all()
    serializer_class = ChecklistItemSerializer
    permission_classes = [HasPermission("edit_audits")]

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
        return Response(EvidenceFileSerializer(item).data, status=status.HTTP_201_CREATED)


class EvidenceFileViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = EvidenceFile.objects.all()
    serializer_class = EvidenceFileSerializer
    permission_classes = [HasPermission("view_audits")]

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        obj = self.get_object()
        if not obj.file:
            return Response({"detail": "No file available."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"url": request.build_absolute_uri(obj.file.url)})


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
    queryset = AuditableEntity.objects.all()
    serializer_class = AuditableEntitySerializer
    permission_classes = [HasPermission("view_audits")]


class RiskHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RiskHistoryEntry.objects.all()
    serializer_class = RiskHistoryEntrySerializer
    permission_classes = [HasPermission("view_audits")]


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request, pk=None):
        item = self.get_object()
        item.read = True
        item.save(update_fields=["read"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="read-all")
    def mark_all_read(self, request):
        self.get_queryset().filter(read=False).update(read=True)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLogEntry.objects.all()
    serializer_class = AuditLogEntrySerializer
    permission_classes = [HasPermission("view_reports")]


class FollowUpViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin):
    queryset = FollowUpItem.objects.select_related("finding").all()
    serializer_class = FollowUpItemSerializer
    permission_classes = [HasPermission("manage_findings")]


class CommentViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.CreateModelMixin):
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


class AuditorViewSet(viewsets.ModelViewSet):
    queryset = Auditor.objects.all()
    serializer_class = AuditorSerializer
    permission_classes = [HasPermission("view_audits")]


class AssignmentViewSet(viewsets.ModelViewSet):
    queryset = AuditAssignment.objects.select_related("auditor", "audit").all()
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


class TimeEntryViewSet(viewsets.ModelViewSet):
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


class HoursBudgetViewSet(viewsets.ModelViewSet):
    queryset = HoursBudget.objects.select_related("audit").all()
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


class RiskAssessmentViewSet(viewsets.ModelViewSet):
    queryset = RiskAssessmentRecord.objects.all()
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
    queryset = RiskAssessmentMatrixCell.objects.all()
    serializer_class = RiskAssessmentMatrixCellSerializer
    permission_classes = [HasPermission("view_audits")]


class RiskAssessmentSummaryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RiskAssessmentSummaryItem.objects.select_related("record").all()
    serializer_class = RiskAssessmentSummaryItemSerializer
    permission_classes = [HasPermission("view_audits")]


class RiskAssessmentImportIssuesViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RiskAssessmentImportIssue.objects.all()
    serializer_class = RiskAssessmentImportIssueSerializer
    permission_classes = [HasPermission("manage_settings")]


class ApprovalRequestViewSet(viewsets.ModelViewSet):
    queryset = ApprovalRequest.objects.prefetch_related("steps").all()
    serializer_class = ApprovalRequestSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        obj = self.get_object()
        comment = request.data.get("comments", "")
        step = obj.steps.filter(status="Pending").order_by("order").first()
        if not step:
            return Response({"detail": "No pending step."}, status=status.HTTP_400_BAD_REQUEST)
        step.status = "Approved"
        step.date = timezone.now().date()
        step.comments = comment or "Approved."
        step.save(update_fields=["status", "date", "comments"])
        obj.current_step = min(obj.current_step + 1, obj.steps.count())
        if not obj.steps.filter(status="Pending").exists() and not obj.steps.filter(status="Rejected").exists():
            obj.status = "Approved"
        obj.save(update_fields=["current_step", "status"])
        return Response(ApprovalRequestSerializer(obj).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        obj = self.get_object()
        comment = request.data.get("comments", "")
        step = obj.steps.filter(status="Pending").order_by("order").first()
        if not step:
            return Response({"detail": "No pending step."}, status=status.HTTP_400_BAD_REQUEST)
        step.status = "Rejected"
        step.date = timezone.now().date()
        step.comments = comment or "Rejected."
        step.save(update_fields=["status", "date", "comments"])
        obj.status = "Rejected"
        obj.save(update_fields=["status"])
        return Response(ApprovalRequestSerializer(obj).data)


class WorkProgramViewSet(viewsets.ModelViewSet):
    queryset = WorkProgram.objects.select_related("audit").prefetch_related("procedures__steps").all()
    permission_classes = [HasPermission("view_audits")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return WorkProgramWriteSerializer
        return WorkProgramSerializer


class WorkProcedureViewSet(viewsets.ModelViewSet):
    queryset = WorkProcedure.objects.select_related("work_program").prefetch_related("steps").all()
    permission_classes = [HasPermission("view_audits")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return WorkProcedureWriteSerializer
        return WorkProcedureSerializer


class WorkProcedureStepViewSet(viewsets.ModelViewSet):
    queryset = WorkProcedureStep.objects.select_related("procedure").all()
    serializer_class = WorkProcedureStepSerializer
    permission_classes = [HasPermission("view_audits")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return WorkProcedureStepWriteSerializer
        return WorkProcedureStepSerializer


class AuditReportViewSet(viewsets.ModelViewSet):
    queryset = AuditReport.objects.select_related("audit").prefetch_related("sections").all()
    permission_classes = [HasPermission("view_reports")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return AuditReportWriteSerializer
        return AuditReportSerializer


class AuditReportSectionViewSet(viewsets.ModelViewSet):
    queryset = AuditReportSection.objects.select_related("report").all()
    permission_classes = [HasPermission("view_reports")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return AuditReportSectionWriteSerializer
        return AuditReportSectionSerializer


class ManagedDocumentViewSet(viewsets.ModelViewSet):
    queryset = ManagedDocument.objects.all()
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [HasPermission("view_reports")]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return ManagedDocumentWriteSerializer
        return ManagedDocumentSerializer
