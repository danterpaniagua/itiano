from django.urls import path

from . import views

urlpatterns = [
    path('', views.notification_list, name='notifications-list'),
    path('<int:pk>/open/', views.open_notification, name='notifications-open'),
    path('mark-all-read/', views.mark_all_read, name='notifications-mark-all-read'),
]
