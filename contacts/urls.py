from django.urls import path
from . import views

urlpatterns = [
    path('', views.contact_list, name='contact-list'),
    path('new/', views.contact_create, name='contact-create'),
    path('<oid:pk>/', views.contact_detail, name='contact-detail'),
    path('<oid:pk>/edit/', views.contact_edit, name='contact-edit'),
    path('<oid:pk>/delete/', views.contact_delete, name='contact-delete'),
    path('<oid:contact_pk>/channels/new/', views.channel_create, name='channel-create'),
    path('<oid:contact_pk>/channels/<oid:pk>/edit/', views.channel_edit, name='channel-edit'),
    path('<oid:contact_pk>/channels/<oid:pk>/delete/', views.channel_delete, name='channel-delete'),
    path('<oid:contact_pk>/channels/<oid:pk>/test/', views.channel_test, name='channel-test'),
]
