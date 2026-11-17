from django.urls import path

from . import views

urlpatterns = [
    path('', views.NoteListView.as_view(), name='notes-list'),
    path('notebook/<oid:notebook_pk>/', views.NoteListView.as_view(), name='notes-notebook'),
    path('mentions/search/', views.MentionSearchView.as_view(), name='notes-mention-search'),
    path('mentions/resolve/', views.MentionResolveView.as_view(), name='notes-mention-resolve'),
    path('new/', views.NoteEditView.as_view(), name='note-new'),
    path('<oid:pk>/edit/', views.NoteEditView.as_view(), name='note-edit'),
    path('<oid:pk>/delete/', views.NoteDeleteView.as_view(), name='note-delete'),
    path('<oid:pk>/share/', views.NoteShareView.as_view(), name='note-share'),
    path('notebook/new/', views.NotebookCreateView.as_view(), name='notebook-new'),
    path('notebook/<oid:pk>/delete/', views.NotebookDeleteView.as_view(), name='notebook-delete'),
]
