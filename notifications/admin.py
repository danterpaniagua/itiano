from django.contrib import admin

from .models import Notification, NotificationRule


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'message', 'source', 'created_at', 'read_at']
    list_filter = ['source']
    search_fields = ['user__username', 'message']
    readonly_fields = ['user', 'message', 'url', 'source', 'created_at']


@admin.register(NotificationRule)
class NotificationRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'grace_minutes', 'starts_at']
    list_filter = ['is_active']
    readonly_fields = ['starts_at', 'created_at', 'updated_at']
