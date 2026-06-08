from django.urls import path

from . import views

urlpatterns = [
    path('', views.clipboard, name='clipboard'),
    path('content/', views.clipboard_content, name='clipboard-content'),
    path('save/', views.clipboard_save, name='clipboard-save'),
]
