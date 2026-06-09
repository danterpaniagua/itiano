from django.urls import path

from . import views

urlpatterns = [
    path('', views.NoteListView.as_view(), name='notes-list'),
    path('notebook/<int:notebook_pk>/', views.NoteListView.as_view(), name='notes-notebook'),
    path('new/', views.NoteEditView.as_view(), name='note-new'),
    path('<int:pk>/edit/', views.NoteEditView.as_view(), name='note-edit'),
    path('<int:pk>/delete/', views.NoteDeleteView.as_view(), name='note-delete'),
    path('<int:pk>/share/', views.NoteShareView.as_view(), name='note-share'),
    path('notebook/new/', views.NotebookCreateView.as_view(), name='notebook-new'),
    path('notebook/<int:pk>/delete/', views.NotebookDeleteView.as_view(), name='notebook-delete'),
]
