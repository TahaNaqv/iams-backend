from django.urls import path, include
from rest_framework.routers import DefaultRouter

from iams.views import (
    ActivityViewSet,
    AssignmentViewSet,
    AuditLogViewSet,
    AuditViewSet,
    AuditableEntityRevisionViewSet,
    AuditableEntityViewSet,
    AuditorViewSet,
    BulkImportJobViewSet,
    BusinessUnitViewSet,
    ChecklistByAuditView,
    ChecklistItemViewSet,
    CommentViewSet,
    CorrectiveActionViewSet,
    EntityRiskViewSet,
    DashboardActivityView,
    DashboardKPIView,
    DashboardRatingSummaryView,
    DashboardRiskHeatmapByDepartmentView,
    DashboardRoleView,
    DashboardTrendsView,
    DashboardUpcomingAuditsView,
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
    TagViewSet,
    IntegrationEventViewSet,
    IntegrationSourceViewSet,
    IntegrationWebhookView,
    KeycloakGroupRoleMapViewSet,
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
    QAIPAssessmentViewSet,
    QAIPFindingViewSet,
    StakeholderSurveyViewSet,
    AuditKPIViewSet,
    QAIPDashboardView,
    CSAQuestionnaireViewSet,
    CSAQuestionViewSet,
    CSAResponseViewSet,
    CSAAnswerViewSet,
    ControlViewSet,
    ControlTestViewSet,
    ControlExceptionViewSet,
    DeficiencyReportViewSet,
    ICFRSummaryView,
    RiskFactorViewSet,
    RiskScoringModelViewSet,
    RiskFactorWeightViewSet,
    EntityRiskScoreViewSet,
    RiskHeatMapView,
    GenerateAuditPlanView,
    ReportJobViewSet,
    GenerateReportView,
    TimeEntryViewSet,
    TimelineByAuditView,
    UserViewSet,
)

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("roles", RoleViewSet, basename="role")
router.register(
    "sso/group-role-maps", KeycloakGroupRoleMapViewSet, basename="sso-group-role-map",
)
# Phase 6 Track 2 — ERP / HR integrations
router.register("integrations/sources", IntegrationSourceViewSet, basename="integration-source")
router.register("integrations/events", IntegrationEventViewSet, basename="integration-event")
router.register("permissions", PermissionViewSet, basename="permission")
router.register("audits", AuditViewSet, basename="audit")
router.register("findings", FindingViewSet, basename="finding")
router.register("corrective-actions", CorrectiveActionViewSet, basename="corrective-action")
router.register("entity-risks", EntityRiskViewSet, basename="entity-risk")
router.register("departments", DepartmentViewSet, basename="department")
router.register("activities", ActivityViewSet, basename="activity")
router.register("checklist-items", ChecklistItemViewSet, basename="checklist-item")
router.register("evidence-files", EvidenceFileViewSet, basename="evidence-file")
router.register("auditable-entities", AuditableEntityViewSet, basename="auditable-entity")
router.register(
    "audit-universe-revisions",
    AuditableEntityRevisionViewSet,
    basename="audit-universe-revision",
)
router.register("business-units", BusinessUnitViewSet, basename="business-unit")
router.register("tags", TagViewSet, basename="tag")
router.register(
    "audit-universe-import-jobs",
    BulkImportJobViewSet,
    basename="audit-universe-import-job",
)
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
# Phase 3 Track 2 — QAIP
router.register("qaip/assessments", QAIPAssessmentViewSet, basename="qaip-assessment")
router.register("qaip/findings", QAIPFindingViewSet, basename="qaip-finding")
router.register("qaip/surveys", StakeholderSurveyViewSet, basename="qaip-survey")
router.register("qaip/kpis", AuditKPIViewSet, basename="qaip-kpi")
# Phase 3 Track 3 — CSA
router.register("csa/questionnaires", CSAQuestionnaireViewSet, basename="csa-questionnaire")
router.register("csa/questions", CSAQuestionViewSet, basename="csa-question")
router.register("csa/responses", CSAResponseViewSet, basename="csa-response")
router.register("csa/answers", CSAAnswerViewSet, basename="csa-answer")
# Phase 3 Track 4 — ICFR
router.register("icfr/controls", ControlViewSet, basename="icfr-control")
router.register("icfr/tests", ControlTestViewSet, basename="icfr-test")
router.register("icfr/exceptions", ControlExceptionViewSet, basename="icfr-exception")
router.register("icfr/deficiencies", DeficiencyReportViewSet, basename="icfr-deficiency")
# Phase 4 Track 1 — Risk Engine
router.register("risk/factors", RiskFactorViewSet, basename="risk-factor")
router.register("risk/models", RiskScoringModelViewSet, basename="risk-scoring-model")
router.register("risk/factor-weights", RiskFactorWeightViewSet, basename="risk-factor-weight")
router.register("risk/scores", EntityRiskScoreViewSet, basename="risk-score")
# Phase 4 Track 2 — Report generation
router.register("reports/jobs", ReportJobViewSet, basename="report-job")

urlpatterns = [
    path("", include(router.urls)),
    path("roles/<uuid:pk>/permissions/", RolePermissionsView.as_view(), name="role-permissions"),
    path("audits/<uuid:audit_id>/checklist/", ChecklistByAuditView.as_view(), name="audit-checklist"),
    path("audits/<uuid:audit_id>/evidence/", EvidenceByAuditView.as_view(), name="audit-evidence"),
    path("audits/<uuid:audit_id>/timeline/", TimelineByAuditView.as_view(), name="audit-timeline"),
    path("dashboard/kpis/", DashboardKPIView.as_view(), name="dashboard-kpis"),
    path("dashboard/trends/", DashboardTrendsView.as_view(), name="dashboard-trends"),
    path(
        "dashboard/risk-heatmap/",
        DashboardRiskHeatmapByDepartmentView.as_view(),
        name="dashboard-risk-heatmap",
    ),
    path("dashboard/ratings/", DashboardRatingSummaryView.as_view(), name="dashboard-ratings"),
    path("dashboard/activity/", DashboardActivityView.as_view(), name="dashboard-activity"),
    path(
        "dashboard/upcoming-audits/",
        DashboardUpcomingAuditsView.as_view(),
        name="dashboard-upcoming-audits",
    ),
    path("dashboard/role/<str:role>/", DashboardRoleView.as_view(), name="dashboard-role"),
    path("qaip/dashboard/", QAIPDashboardView.as_view(), name="qaip-dashboard"),
    path("icfr/summary/", ICFRSummaryView.as_view(), name="icfr-summary"),
    path("risk/heat-map/", RiskHeatMapView.as_view(), name="risk-heat-map"),
    path("risk/generate-plan/", GenerateAuditPlanView.as_view(), name="risk-generate-plan"),
    path("reports/generate/", GenerateReportView.as_view(), name="reports-generate"),
    path(
        "risk-assessment-import/issues/",
        RiskAssessmentImportIssuesViewSet.as_view({"get": "list"}),
        name="risk-assessment-import-issues",
    ),
    # Phase 6 Track 2 — inbound webhook ingestion (HMAC-signed)
    path(
        "integrations/webhooks/<uuid:source_id>/<str:resource>/",
        IntegrationWebhookView.as_view(),
        name="integration-webhook",
    ),
]
