from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path('', views.SettingsIndexView.as_view(), name='settings-index'),
    path('tags/', views.TagListView.as_view(), name='settings-tags'),
    path('tags/create/', views.TagCreateView.as_view(), name='settings-tag-create'),
    path('tags/<int:pk>/edit/', views.TagEditView.as_view(), name='settings-tag-edit'),
    path('tags/<int:pk>/delete/', views.TagDeleteView.as_view(), name='settings-tag-delete'),
    path('categories/', views.CategoryListView.as_view(), name='settings-categories'),
    path('categories/create/', views.CategoryCreateView.as_view(), name='settings-category-create'),
    path('categories/<int:pk>/edit/', views.CategoryEditView.as_view(), name='settings-category-edit'),
    path('categories/<int:pk>/delete/', views.CategoryDeleteView.as_view(), name='settings-category-delete'),
    path('user/', views.UserSettingsView.as_view(), name='settings-user'),
    path('user/channels/add/', views.UserChannelCreateView.as_view(), name='settings-user-channel-add'),
    path('user/channels/<int:pk>/edit/', views.UserChannelEditView.as_view(), name='settings-user-channel-edit'),
    path('user/channels/<int:pk>/delete/', views.UserChannelDeleteView.as_view(), name='settings-user-channel-delete'),
    path('app/', views.AppSettingsView.as_view(), name='settings-app'),
]
