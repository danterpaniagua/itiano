from django.contrib import admin

from .models import JiraEvent, JiraTicket


class JiraEventInline(admin.TabularInline):
    model = JiraEvent
    extra = 0
    readonly_fields = ('event_type', 'summary', 'received_at')
    can_delete = False


@admin.register(JiraTicket)
class JiraTicketAdmin(admin.ModelAdmin):
    list_display = ('issue_key', 'title', 'project_key', 'issue_type', 'status', 'parent_key', 'updated_at')
    search_fields = ('issue_key', 'title', 'parent_key')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [JiraEventInline]


@admin.register(JiraEvent)
class JiraEventAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'event_type', 'summary', 'received_at')
    readonly_fields = ('ticket', 'event_type', 'summary', 'payload', 'received_at')
