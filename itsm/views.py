from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import JsonResponse
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

        selected_tags = request.GET.getlist('tags')
        selected_statuses = request.GET.getlist('statuses')
        q_filter = request.GET.get('q', '').strip()
        for tag_name in selected_tags:
            tickets = tickets.filter(tags__name=tag_name)
        if selected_statuses:
            tickets = tickets.filter(state__in=selected_statuses)
        if q_filter:
            tickets = tickets.filter(title__icontains=q_filter)

        all_states = [
            {'value': v, 'label': l}
            for v, l in Ticket.STATES
        ]

        tickets = tickets.select_related('requester', 'assigned_to').prefetch_related('tags').order_by('-created_at')
        return render(request, 'itsm/ticket_list.html', {
            'tickets': tickets,
            'all_tags': Tag.objects.all(),
            'selected_tags': selected_tags,
            'selected_statuses': selected_statuses,
            'all_states': all_states,
            'q_filter': q_filter,
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

        jira_ticket = None
        jira_attachments = []
        jira_events = []
        jira_parent_data = None
        jira_children = []
        if ticket.external_id:
            from jira_integration.models import JiraTicket
            jira_ticket = JiraTicket.objects.filter(issue_key=ticket.external_id).first()
            if jira_ticket:
                last_event = jira_ticket.events.order_by('-received_at').first()
                last_payload = last_event.payload if last_event else None
                if last_payload:
                    fields = (last_payload.get('issue') or {}).get('fields') or {}
                    jira_attachments = sorted(
                        fields.get('attachment') or [],
                        key=lambda a: a.get('created', ''),
                        reverse=True,
                    )
                jira_events = list(jira_ticket.events.order_by('-received_at'))

                if jira_ticket.parent_key:
                    parent_obj = JiraTicket.objects.filter(issue_key=jira_ticket.parent_key).first()
                    if parent_obj:
                        jira_parent_data = {
                            'ticket': parent_obj,
                            'issue_key': parent_obj.issue_key,
                            'title': parent_obj.title,
                            'status': parent_obj.status,
                            'issue_type': parent_obj.issue_type,
                        }
                    else:
                        raw = {}
                        if last_payload:
                            raw = (last_payload.get('issue') or {}).get('fields', {}).get('parent') or {}
                        jira_parent_data = {
                            'ticket': None,
                            'issue_key': jira_ticket.parent_key,
                            'title': (raw.get('fields') or {}).get('summary', ''),
                            'status': ((raw.get('fields') or {}).get('status') or {}).get('name', ''),
                            'issue_type': ((raw.get('fields') or {}).get('issuetype') or {}).get('name', ''),
                        }

                children_in_db = list(JiraTicket.objects.filter(parent_key=jira_ticket.issue_key))
                children_in_db_keys = {c.issue_key for c in children_in_db}
                jira_children = [
                    {'ticket': c, 'issue_key': c.issue_key, 'title': c.title,
                     'status': c.status, 'issue_type': c.issue_type}
                    for c in children_in_db
                ]
                if last_payload:
                    for sub in (last_payload.get('issue') or {}).get('fields', {}).get('subtasks') or []:
                        key = sub.get('key', '')
                        if key and key not in children_in_db_keys:
                            f = sub.get('fields') or {}
                            jira_children.append({
                                'ticket': None,
                                'issue_key': key,
                                'title': f.get('summary', ''),
                                'status': (f.get('status') or {}).get('name', ''),
                                'issue_type': (f.get('issuetype') or {}).get('name', ''),
                            })

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
            'jira_ticket': jira_ticket,
            'jira_attachments': jira_attachments,
            'jira_events': jira_events,
            'jira_parent_data': jira_parent_data,
            'jira_children': jira_children,
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
        name = request.POST.get('tag_name', '').strip()
        color = request.POST.get('tag_color', '').strip()
        if name:
            tag, _ = Tag.objects.get_or_create(name=name)
            if color and tag.color != color:
                tag.color = color
                tag.save(update_fields=['color'])
            TicketTag.objects.get_or_create(ticket=ticket, tag=tag, defaults={'source': TicketTag.SOURCE_MANUAL})
        return redirect('ticket-detail', pk=pk)


class TicketTagRemoveView(LoginRequiredMixin, View):
    def post(self, request, pk, tag_pk):
        ticket = get_object_or_404(Ticket, pk=pk)
        if not can_edit_ticket(request.user, ticket):
            raise PermissionDenied
        TicketTag.objects.filter(ticket=ticket, tag_id=tag_pk, source=TicketTag.SOURCE_MANUAL).delete()
        return redirect('ticket-detail', pk=pk)


class TagAutocompleteView(LoginRequiredMixin, View):
    def get(self, request):
        if not request.user.is_staff:
            raise PermissionDenied
        q = request.GET.get('q', '').strip()
        tags = Tag.objects.filter(name__icontains=q)[:10] if q else Tag.objects.all()[:10]
        return JsonResponse({'results': [{'name': t.name, 'color': t.display_color} for t in tags]})


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
