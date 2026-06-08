from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('docs/', views.docs, name='docs'),
    path('health/', views.health, name='health'),
]
