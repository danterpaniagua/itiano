from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .forms import CommentForm, TicketEditForm, TicketForm
from .models import Ticket, TicketEvent
from .permissions import can_comment, can_edit_ticket, can_view_ticket
from .transitions import TRANSITION_LABELS, get_available_transitions, perform_transition


class TicketListView(LoginRequiredMixin, View):
    def get(self, request):
        from core.models import UserProfile
        profile, _ = UserProfile.objects.get_or_create(
            user=request.user,
            defaults={'role': 'admin' if request.user.is_superuser else 'requester'},
        )
        role = profile.role
        if role in ('manager', 'admin'):
            tickets = Ticket.objects.all()
        elif role == 'agent':
            tickets = Ticket.objects.filter(
                Q(assigned_to=request.user) | Q(state=Ticket.STATE_NEW, assigned_to__isnull=True)
            )
        else:
            tickets = Ticket.objects.filter(requester=request.user)

        tickets = tickets.select_related('requester', 'assigned_to').order_by('-created_at')
        return render(request, 'itsm/ticket_list.html', {'tickets': tickets})


class TicketCreateView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'itsm/ticket_create.html', {'form': TicketForm()})

    def post(self, request):
        form = TicketForm(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.requester = request.user
            ticket.state = Ticket.STATE_NEW
            ticket.save()
            TicketEvent.objects.create(
                ticket=ticket,
                actor=request.user,
                from_state='',
                to_state=Ticket.STATE_NEW,
                note='Ticket created.',
            )
            messages.success(request, 'Ticket created.')
            return redirect('ticket-detail', pk=ticket.pk)
        return render(request, 'itsm/ticket_create.html', {'form': form})


class TicketDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        ticket = get_object_or_404(Ticket, pk=pk)
        if not can_view_ticket(request.user, ticket):
            raise PermissionDenied

        raw_transitions = get_available_transitions(ticket, request.user)
        available_transitions = [
            {'state': t, 'label': TRANSITION_LABELS.get(t, t.replace('_', ' ').title())}
            for t in raw_transitions
        ]

        return render(request, 'itsm/ticket_detail.html', {
            'ticket': ticket,
            'events': ticket.events.select_related('actor').all(),
            'comments': ticket.comments.select_related('author').all(),
            'available_transitions': available_transitions,
            'can_comment': can_comment(request.user, ticket),
            'can_edit': can_edit_ticket(request.user, ticket),
            'comment_form': CommentForm(),
        })


class TransitionView(LoginRequiredMixin, View):
    def post(self, request, pk):
        ticket = get_object_or_404(Ticket, pk=pk)
        if not can_view_ticket(request.user, ticket):
            raise PermissionDenied

        to_state = request.POST.get('to_state', '')
        try:
            perform_transition(ticket, to_state, request.user)
            messages.success(request, f'Ticket moved to {to_state.replace("_", " ")}.')
        except PermissionError as e:
            messages.error(request, str(e))

        return redirect('ticket-detail', pk=pk)


class CommentCreateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        ticket = get_object_or_404(Ticket, pk=pk)
        if not can_comment(request.user, ticket):
            raise PermissionDenied

        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.ticket = ticket
            comment.author = request.user
            comment.save()

        return redirect('ticket-detail', pk=pk)


_TRACKED_FIELDS = ['title', 'description', 'type', 'priority', 'category', 'service', 'sub_service']


def _field_display(ticket, field):
    value = getattr(ticket, field, None)
    if value is None:
        return ''
    return str(value)


class TicketEditView(LoginRequiredMixin, View):
    def _get_ticket(self, request, pk):
        ticket = get_object_or_404(Ticket, pk=pk)
        if not can_edit_ticket(request.user, ticket):
            raise PermissionDenied
        return ticket

    def get(self, request, pk):
        ticket = self._get_ticket(request, pk)
        form = TicketEditForm(instance=ticket)
        return render(request, 'itsm/ticket_edit.html', {'ticket': ticket, 'form': form})

    def post(self, request, pk):
        ticket = self._get_ticket(request, pk)
        old_values = {f: _field_display(ticket, f) for f in _TRACKED_FIELDS}

        form = TicketEditForm(request.POST, instance=ticket)
        if not form.is_valid():
            return render(request, 'itsm/ticket_edit.html', {'ticket': ticket, 'form': form})

        form.save()
        ticket.refresh_from_db()

        for field in _TRACKED_FIELDS:
            new_val = _field_display(ticket, field)
            if old_values[field] != new_val:
                TicketEvent.objects.create(
                    ticket=ticket,
                    actor=request.user,
                    field_name=field,
                    old_value=old_values[field],
                    new_value=new_val,
                )

        messages.success(request, 'Ticket updated.')
        return redirect('ticket-detail', pk=pk)
