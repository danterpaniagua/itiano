from django.contrib import admin

from .models import Action, Trigger, TriggerLog


class TriggerInline(admin.TabularInline):
    model = Trigger
    extra = 0
    fields = ('name', 'source', 'is_active')
    show_change_link = True


@admin.register(Action)
class ActionAdmin(admin.ModelAdmin):
    list_display = ('name', 'action_type', 'system_user', 'is_active', 'updated_at')
    list_filter = ('action_type', 'is_active')
    list_editable = ('is_active',)
    search_fields = ('name',)
    inlines = [TriggerInline]
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Trigger)
class TriggerAdmin(admin.ModelAdmin):
    list_display = ('name', 'source', 'action', 'is_active', 'updated_at')
    list_filter = ('source', 'is_active')
    list_editable = ('is_active',)
    search_fields = ('name', 'action__name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(TriggerLog)
class TriggerLogAdmin(admin.ModelAdmin):
    list_display = ('trigger', 'action', 'result', 'created_at')
    list_filter = ('result', 'trigger__source')
    search_fields = ('trigger__name', 'action__name', 'detail')
    readonly_fields = ('trigger', 'action', 'payload_snapshot', 'result', 'detail', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
