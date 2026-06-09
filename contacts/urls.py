from django.urls import path
from . import views

urlpatterns = [
    path('', views.contact_list, name='contact-list'),
    path('new/', views.contact_create, name='contact-create'),
    path('<int:pk>/', views.contact_detail, name='contact-detail'),
    path('<int:pk>/edit/', views.contact_edit, name='contact-edit'),
    path('<int:pk>/delete/', views.contact_delete, name='contact-delete'),
    path('<int:contact_pk>/channels/new/', views.channel_create, name='channel-create'),
    path('<int:contact_pk>/channels/<int:pk>/edit/', views.channel_edit, name='channel-edit'),
    path('<int:contact_pk>/channels/<int:pk>/delete/', views.channel_delete, name='channel-delete'),
    path('<int:contact_pk>/channels/<int:pk>/test/', views.channel_test, name='channel-test'),
]
