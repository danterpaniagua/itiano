from django.urls import path

from . import views

urlpatterns = [
    path('', views.TimeEntryListView.as_view(), name='timetracking-list'),
    path('create/', views.TimeEntryCreateView.as_view(), name='timetracking-create'),
    path('<int:pk>/edit/', views.TimeEntryEditView.as_view(), name='timetracking-edit'),
    path('<int:pk>/delete/', views.TimeEntryDeleteView.as_view(), name='timetracking-delete'),
    path('report/', views.DailyReportView.as_view(), name='timetracking-report'),
]
