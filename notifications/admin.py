from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'message', 'source', 'created_at', 'read_at']
    list_filter = ['source']
    search_fields = ['user__username', 'message']
    readonly_fields = ['user', 'message', 'url', 'source', 'created_at']
