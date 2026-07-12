from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path('', views.UserSettingsView.as_view(), name='settings-user'),
    path('user/', RedirectView.as_view(pattern_name='settings-user', permanent=False)),
    path('user/channels/add/', views.UserChannelCreateView.as_view(), name='settings-user-channel-add'),
    path('user/channels/<int:pk>/edit/', views.UserChannelEditView.as_view(), name='settings-user-channel-edit'),
    path('user/channels/<int:pk>/delete/', views.UserChannelDeleteView.as_view(), name='settings-user-channel-delete'),
    path('app/', views.AppSettingsHubView.as_view(), name='settings-app'),
    path('time-report/', views.TimeReportSettingsView.as_view(), name='settings-time-report'),
    path('jira/', views.JiraSettingsView.as_view(), name='settings-jira'),
    path('jira/status/add/', views.JiraStatusAddView.as_view(), name='settings-jira-status-add'),
    path('jira/status/<int:pk>/delete/', views.JiraStatusDeleteView.as_view(), name='settings-jira-status-delete'),
    path('jira/status/<int:pk>/toggle-terminal/', views.JiraStatusToggleTerminalView.as_view(), name='settings-jira-status-toggle-terminal'),
    path('tickets/', views.TicketsSettingsView.as_view(), name='settings-tickets'),
    path('tags/', views.TagListView.as_view(), name='settings-tags'),
    path('tags/create/', views.TagCreateView.as_view(), name='settings-tag-create'),
    path('tags/<int:pk>/edit/', views.TagEditView.as_view(), name='settings-tag-edit'),
    path('tags/<int:pk>/delete/', views.TagDeleteView.as_view(), name='settings-tag-delete'),
    path('categories/', views.CategoryListView.as_view(), name='settings-categories'),
    path('categories/create/', views.CategoryCreateView.as_view(), name='settings-category-create'),
    path('categories/<int:pk>/edit/', views.CategoryEditView.as_view(), name='settings-category-edit'),
    path('categories/<int:pk>/delete/', views.CategoryDeleteView.as_view(), name='settings-category-delete'),
    path('vault/', views.VaultSettingsView.as_view(), name='settings-vault'),
    path('vault/teams/create/', views.TeamCreateView.as_view(), name='settings-vault-team-create'),
    path('vault/teams/<int:pk>/edit/', views.TeamEditView.as_view(), name='settings-vault-team-edit'),
    path('vault/teams/<int:pk>/members/add/', views.TeamMemberAddView.as_view(), name='settings-vault-team-member-add'),
    path('vault/teams/<int:pk>/members/<int:user_pk>/remove/', views.TeamMemberRemoveView.as_view(), name='settings-vault-team-member-remove'),
    path('vault/containers/create/', views.ContainerCreateView.as_view(), name='settings-vault-container-create'),
    path('vault/containers/<int:pk>/edit/', views.ContainerEditView.as_view(), name='settings-vault-container-edit'),
    path('vault/containers/<int:pk>/delete/', views.ContainerDeleteView.as_view(), name='settings-vault-container-delete'),
    path('vault/containers/<int:pk>/access/add/', views.ContainerAccessAddView.as_view(), name='settings-vault-access-add'),
    path('vault/containers/<int:pk>/access/<int:access_pk>/edit/', views.ContainerAccessLevelEditView.as_view(), name='settings-vault-access-edit'),
    path('vault/containers/<int:pk>/access/<int:access_pk>/remove/', views.ContainerAccessRemoveView.as_view(), name='settings-vault-access-remove'),
]
