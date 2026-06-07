from django.contrib import admin

from .models import ClipboardEntry


@admin.register(ClipboardEntry)
class ClipboardEntryAdmin(admin.ModelAdmin):
    list_display = ('user', 'updated_at')
    readonly_fields = ('user', 'updated_at')
