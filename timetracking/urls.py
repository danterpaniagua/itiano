from django.urls import path

from . import map_views, tag_report_views, views

urlpatterns = [
    path('', views.TimeEntryListView.as_view(), name='timetracking-list'),
    path('create/', views.TimeEntryCreateView.as_view(), name='timetracking-create'),
    path('<oid:pk>/edit/', views.TimeEntryEditView.as_view(), name='timetracking-edit'),
    path('<oid:pk>/delete/', views.TimeEntryDeleteView.as_view(), name='timetracking-delete'),
    path('current/', views.DailyReportView.as_view(), name='timetracking-current'),
    path('current/ticket/<str:issue_key>/', views.TicketTimelineView.as_view(), name='timetracking-ticket-timeline'),
    path('report/', tag_report_views.TimeReportView.as_view(), name='timetracking-report'),
    path('report/prompt/', tag_report_views.TimeReportPromptView.as_view(), name='timetracking-report-prompt'),
    path('map/', map_views.TimeMapView.as_view(), name='timetracking-map'),
    path('schedule/', views.WorkScheduleView.as_view(), name='timetracking-schedule'),
]
