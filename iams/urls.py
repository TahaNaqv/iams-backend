from django.urls import path, include
from rest_framework.routers import DefaultRouter

from iams.views import (
    ActivityViewSet,
    AssignmentViewSet,
    AuditLogViewSet,
    AuditViewSet,
    AuditableEntityViewSet,
    AuditorViewSet,
    ChecklistByAuditView,
    ChecklistItemViewSet,
    CommentViewSet,
    CorrectiveActionViewSet,
    DashboardKPIView,
    DepartmentViewSet,
    EvidenceByAuditView,
    EvidenceFileViewSet,
    FindingViewSet,
    FollowUpViewSet,
    HoursBudgetViewSet,
    NotificationPreferenceViewSet,
    NotificationViewSet,
    PermissionViewSet,
    RiskAssessmentImportIssuesViewSet,
    RiskAssessmentMatrixViewSet,
    RiskAssessmentSheetsViewSet,
    RiskAssessmentSummaryViewSet,
    RiskAssessmentViewSet,
    RiskHistoryViewSet,
    RolePermissionsView,
    RoleViewSet,
    ApprovalChainTemplateViewSet,
    ApprovalRequestViewSet,
    WorkProgramViewSet,
    WorkProcedureViewSet,
    WorkProcedureStepViewSet,
    AuditReportViewSet,
    AuditReportSectionViewSet,
    ManagedDocumentViewSet,
    WorkingPaperViewSet,
    TimeEntryViewSet,
    TimelineByAuditView,
    UserViewSet,
)

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("roles", RoleViewSet, basename="role")
router.register("permissions", PermissionViewSet, basename="permission")
router.register("audits", AuditViewSet, basename="audit")
router.register("findings", FindingViewSet, basename="finding")
router.register("corrective-actions", CorrectiveActionViewSet, basename="corrective-action")
router.register("departments", DepartmentViewSet, basename="department")
router.register("activities", ActivityViewSet, basename="activity")
router.register("checklist-items", ChecklistItemViewSet, basename="checklist-item")
router.register("evidence-files", EvidenceFileViewSet, basename="evidence-file")
router.register("auditable-entities", AuditableEntityViewSet, basename="auditable-entity")
router.register("risk-history", RiskHistoryViewSet, basename="risk-history")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("notification-preferences", NotificationPreferenceViewSet, basename="notification-preference")
router.register("audit-log", AuditLogViewSet, basename="audit-log")
router.register("follow-ups", FollowUpViewSet, basename="follow-up")
router.register("comments", CommentViewSet, basename="comment")
router.register("auditors", AuditorViewSet, basename="auditor")
router.register("assignments", AssignmentViewSet, basename="assignment")
router.register("time-entries", TimeEntryViewSet, basename="time-entry")
router.register("hours-budgets", HoursBudgetViewSet, basename="hours-budget")
router.register("risk-assessments", RiskAssessmentViewSet, basename="risk-assessment")
router.register("risk-assessment-sheets", RiskAssessmentSheetsViewSet, basename="risk-assessment-sheet")
router.register("risk-assessment-matrix", RiskAssessmentMatrixViewSet, basename="risk-assessment-matrix")
router.register("risk-assessment-summary", RiskAssessmentSummaryViewSet, basename="risk-assessment-summary")
router.register("approval-requests", ApprovalRequestViewSet, basename="approval-request")
router.register("approval-chain-templates", ApprovalChainTemplateViewSet, basename="approval-chain-template")
router.register("work-programs", WorkProgramViewSet, basename="work-program")
router.register("work-procedures", WorkProcedureViewSet, basename="work-procedure")
router.register("work-procedure-steps", WorkProcedureStepViewSet, basename="work-procedure-step")
router.register("audit-reports", AuditReportViewSet, basename="audit-report")
router.register("audit-report-sections", AuditReportSectionViewSet, basename="audit-report-section")
router.register("managed-documents", ManagedDocumentViewSet, basename="managed-document")
router.register("working-papers", WorkingPaperViewSet, basename="working-paper")

urlpatterns = [
    path("", include(router.urls)),
    path("roles/<uuid:pk>/permissions/", RolePermissionsView.as_view(), name="role-permissions"),
    path("audits/<uuid:audit_id>/checklist/", ChecklistByAuditView.as_view(), name="audit-checklist"),
    path("audits/<uuid:audit_id>/evidence/", EvidenceByAuditView.as_view(), name="audit-evidence"),
    path("audits/<uuid:audit_id>/timeline/", TimelineByAuditView.as_view(), name="audit-timeline"),
    path("dashboard/kpis/", DashboardKPIView.as_view(), name="dashboard-kpis"),
    path(
        "risk-assessment-import/issues/",
        RiskAssessmentImportIssuesViewSet.as_view({"get": "list"}),
        name="risk-assessment-import-issues",
    ),
]
