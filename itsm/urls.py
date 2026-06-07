from django.urls import path

from . import views

urlpatterns = [
    path('', views.TicketListView.as_view(), name='ticket-list'),
    path('new/', views.TicketCreateView.as_view(), name='ticket-create'),
    path('<int:pk>/', views.TicketDetailView.as_view(), name='ticket-detail'),
    path('<int:pk>/transition/', views.TransitionView.as_view(), name='ticket-transition'),
    path('<int:pk>/comment/', views.CommentCreateView.as_view(), name='ticket-comment'),
    path('<int:pk>/edit/', views.TicketEditView.as_view(), name='ticket-edit'),
]
