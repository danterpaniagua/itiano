from django.urls import path

from . import views

urlpatterns = [
    path('', views.credential_list, name='vault-list'),
    path('new/', views.credential_create, name='vault-create'),
    path('<int:pk>/edit/', views.credential_edit, name='vault-edit'),
    path('<int:pk>/delete/', views.credential_delete, name='vault-delete'),
    path('<int:pk>/copy/', views.credential_copy, name='vault-copy'),
]
