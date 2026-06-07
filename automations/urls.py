from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='automations-index'),
    path('actions/', views.action_list, name='automations-action-list'),
    path('actions/new/', views.action_create, name='automations-action-create'),
    path('actions/<int:pk>/edit/', views.action_edit, name='automations-action-edit'),
    path('actions/<int:pk>/toggle/', views.action_toggle, name='automations-action-toggle'),
    path('triggers/', views.trigger_list, name='automations-trigger-list'),
    path('triggers/new/', views.trigger_create, name='automations-trigger-create'),
    path('triggers/<int:pk>/edit/', views.trigger_edit, name='automations-trigger-edit'),
    path('triggers/<int:pk>/toggle/', views.trigger_toggle, name='automations-trigger-toggle'),
    path('logs/', views.log_list, name='automations-log-list'),
]
