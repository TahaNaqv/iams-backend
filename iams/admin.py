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
    EvidenceFile,
    Finding,
    FollowUpItem,
    HoursBudget,
    Notification,
    Permission,
    RiskAssessmentImportIssue,
    RiskAssessmentImportJob,
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
admin.site.register(Audit)
admin.site.register(Finding)
admin.site.register(CorrectiveAction)
admin.site.register(ActivityItem)
admin.site.register(ChecklistItem)
admin.site.register(EvidenceFile)
admin.site.register(TimelineEvent)
admin.site.register(AuditableEntity)


@admin.register(RiskHistoryEntry)
class RiskHistoryEntryAdmin(admin.ModelAdmin):
    """Read-only in the admin — RiskHistoryEntry is append-only (the model
    rejects updates/deletes), so surfacing edit forms would only 500."""

    list_display = ("entity", "date", "previous_rating", "current_rating")
    list_filter = ("current_rating", "date")
    search_fields = ("entity",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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
admin.site.register(RiskAssessmentImportJob)

# Register your models here.
