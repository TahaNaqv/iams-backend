from django.contrib import admin

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
    Permission,
    RiskAssessmentImportIssue,
    RiskAssessmentMatrixCell,
    RiskAssessmentRecord,
    RiskAssessmentSheet,
    RiskAssessmentSummaryItem,
    RiskHistoryEntry,
    Role,
    TimeEntry,
    TimelineEvent,
    UserProfile,
)

admin.site.register(Permission)
admin.site.register(Role)
admin.site.register(UserProfile)
admin.site.register(Department)
admin.site.register(Audit)
admin.site.register(Finding)
admin.site.register(CorrectiveAction)
admin.site.register(ActivityItem)
admin.site.register(ChecklistItem)
admin.site.register(EvidenceFile)
admin.site.register(TimelineEvent)
admin.site.register(AuditableEntity)
admin.site.register(RiskHistoryEntry)
admin.site.register(Notification)
admin.site.register(AuditLogEntry)
admin.site.register(FollowUpItem)
admin.site.register(Comment)
admin.site.register(Auditor)
admin.site.register(AuditAssignment)
admin.site.register(TimeEntry)
admin.site.register(HoursBudget)
admin.site.register(RiskAssessmentSheet)
admin.site.register(RiskAssessmentRecord)
admin.site.register(RiskAssessmentMatrixCell)
admin.site.register(RiskAssessmentSummaryItem)
admin.site.register(RiskAssessmentImportIssue)

# Register your models here.
