from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .forms import CommentForm, TicketEditForm, TicketForm
from .models import Tag, Ticket, TicketAttachment, TicketEvent, TicketTag
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

        tag_filter = request.GET.get('tag', '')
        if tag_filter:
            tickets = tickets.filter(tags__name=tag_filter)

        tickets = tickets.select_related('requester', 'assigned_to').prefetch_related('tags').order_by('-created_at')
        return render(request, 'itsm/ticket_list.html', {
            'tickets': tickets,
            'all_tags': Tag.objects.all(),
            'tag_filter': tag_filter,
        })


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

        ticket_tags = ticket.ticket_tags.select_related('tag').all()
        assigned_tag_ids = {tt.tag_id for tt in ticket_tags}
        addable_tags = Tag.objects.exclude(pk__in=assigned_tag_ids)

        return render(request, 'itsm/ticket_detail.html', {
            'ticket': ticket,
            'events': ticket.events.select_related('actor').all(),
            'comments': ticket.comments.select_related('author').all(),
            'available_transitions': available_transitions,
            'can_comment': can_comment(request.user, ticket),
            'can_edit': can_edit_ticket(request.user, ticket),
            'comment_form': CommentForm(),
            'ticket_tags': ticket_tags,
            'addable_tags': addable_tags,
            'attachments': ticket.attachments.select_related('uploaded_by').all(),
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

        if not form.has_changed():
            messages.info(request, 'No changes detected.')
            return redirect('ticket-detail', pk=pk)

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


class TicketTagAddView(LoginRequiredMixin, View):
    def post(self, request, pk):
        ticket = get_object_or_404(Ticket, pk=pk)
        if not can_edit_ticket(request.user, ticket):
            raise PermissionDenied
        tag_id = request.POST.get('tag_id')
        if tag_id:
            tag = get_object_or_404(Tag, pk=tag_id)
            TicketTag.objects.get_or_create(ticket=ticket, tag=tag, defaults={'source': TicketTag.SOURCE_MANUAL})
        return redirect('ticket-detail', pk=pk)


class TicketTagRemoveView(LoginRequiredMixin, View):
    def post(self, request, pk, tag_pk):
        ticket = get_object_or_404(Ticket, pk=pk)
        if not can_edit_ticket(request.user, ticket):
            raise PermissionDenied
        TicketTag.objects.filter(ticket=ticket, tag_id=tag_pk, source=TicketTag.SOURCE_MANUAL).delete()
        return redirect('ticket-detail', pk=pk)


class AttachmentUploadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        ticket = get_object_or_404(Ticket, pk=pk)
        if not can_view_ticket(request.user, ticket):
            raise PermissionDenied

        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            messages.error(request, 'No file provided.')
            return redirect('ticket-detail', pk=pk)

        max_size = getattr(settings, 'MAX_UPLOAD_SIZE', 10 * 1024 * 1024)
        if uploaded_file.size > max_size:
            messages.error(request, f'File too large. Maximum size is {max_size // (1024 * 1024)} MB.')
            return redirect('ticket-detail', pk=pk)

        TicketAttachment.objects.create(
            ticket=ticket,
            file=uploaded_file,
            original_name=uploaded_file.name[:255],
            file_size=uploaded_file.size,
            uploaded_by=request.user,
        )
        return redirect('ticket-detail', pk=pk)


class AttachmentDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk, att_pk):
        ticket = get_object_or_404(Ticket, pk=pk)
        attachment = get_object_or_404(TicketAttachment, pk=att_pk, ticket=ticket)

        if attachment.uploaded_by != request.user and not request.user.is_staff:
            raise PermissionDenied

        attachment.file.delete(save=False)
        attachment.delete()
        return redirect('ticket-detail', pk=pk)
