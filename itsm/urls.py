from django.urls import path

from . import views

urlpatterns = [
    path('', views.TicketListView.as_view(), name='ticket-list'),
    path('new/', views.TicketCreateView.as_view(), name='ticket-create'),
    path('<oid:pk>/', views.TicketDetailView.as_view(), name='ticket-detail'),
    path('<oid:pk>/transition/', views.TransitionView.as_view(), name='ticket-transition'),
    path('<oid:pk>/comment/', views.CommentCreateView.as_view(), name='ticket-comment'),
    path('<oid:pk>/edit/', views.TicketEditView.as_view(), name='ticket-edit'),
    path('<oid:pk>/tags/add/', views.TicketTagAddView.as_view(), name='ticket-tag-add'),
    path('<oid:pk>/tags/<oid:tag_pk>/remove/', views.TicketTagRemoveView.as_view(), name='ticket-tag-remove'),
    path('tags/autocomplete/', views.TagAutocompleteView.as_view(), name='tag-autocomplete'),
    path('<oid:pk>/attachments/upload/', views.AttachmentUploadView.as_view(), name='ticket-attachment-upload'),
    path('<oid:pk>/attachments/<oid:att_pk>/delete/', views.AttachmentDeleteView.as_view(), name='ticket-attachment-delete'),
]
