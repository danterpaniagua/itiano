from django.contrib import admin

from .models import AppSetting, JiraStatusConfig


@admin.register(AppSetting)
class AppSettingAdmin(admin.ModelAdmin):
    list_display = ('key', 'value')
    search_fields = ('key',)


@admin.register(JiraStatusConfig)
class JiraStatusConfigAdmin(admin.ModelAdmin):
    list_display = ('status_name', 'category')
    list_filter = ('category',)
