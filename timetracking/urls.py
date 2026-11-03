from django.urls import path
from django.views.generic import RedirectView

from . import map_views, views

urlpatterns = [
    path('', views.TimeEntryListView.as_view(), name='timetracking-list'),
    path('create/', views.TimeEntryCreateView.as_view(), name='timetracking-create'),
    path('<int:pk>/edit/', views.TimeEntryEditView.as_view(), name='timetracking-edit'),
    path('<int:pk>/delete/', views.TimeEntryDeleteView.as_view(), name='timetracking-delete'),
    path('current/', views.DailyReportView.as_view(), name='timetracking-current'),
    path('current/ticket/<str:issue_key>/', views.TicketTimelineView.as_view(), name='timetracking-ticket-timeline'),
    # Temporary: old bookmarks and notifications keep working until v5.21.0 gives /time/report/ to the new report.
    path('report/', RedirectView.as_view(pattern_name='timetracking-current', query_string=True)),
    path('report/ticket/<str:issue_key>/', RedirectView.as_view(pattern_name='timetracking-ticket-timeline', query_string=True)),
    path('map/', map_views.TimeMapView.as_view(), name='timetracking-map'),
    path('schedule/', views.WorkScheduleView.as_view(), name='timetracking-schedule'),
]
