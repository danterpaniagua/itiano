from django.contrib import admin

from .models import ReportEnvironment, ReportProject, ReportService


class ReportServiceInline(admin.TabularInline):
    model = ReportService
    extra = 0


class ReportEnvironmentInline(admin.TabularInline):
    model = ReportEnvironment
    extra = 0


@admin.register(ReportProject)
class ReportProjectAdmin(admin.ModelAdmin):
    list_display = ['tag_name']
    inlines = [ReportServiceInline]


@admin.register(ReportService)
class ReportServiceAdmin(admin.ModelAdmin):
    list_display = ['tag_name', 'project']
    list_filter = ['project']
    inlines = [ReportEnvironmentInline]


@admin.register(ReportEnvironment)
class ReportEnvironmentAdmin(admin.ModelAdmin):
    list_display = ['tag_name', 'service']
    list_filter = ['service__project']
