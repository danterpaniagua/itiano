from django.urls import path

from . import views

urlpatterns = [
    path('webhook/', views.webhook, name='jira-webhook'),
    path('', views.ticket_list, name='jira-ticket-list'),
    path('<str:issue_key>/', views.ticket_detail, name='jira-ticket-detail'),
    path('<str:issue_key>/sandbox/<int:event_pk>/', views.open_in_sandbox, name='jira-open-sandbox'),
    path('<str:issue_key>/resend/<int:event_pk>/', views.resend_event, name='jira-resend-event'),
    path('<str:issue_key>/toggle-deleted/', views.toggle_deleted, name='jira-toggle-deleted'),
]
