import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import OuterRef, Subquery
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from .models import JiraEvent, JiraTicket

logger = logging.getLogger(__name__)


def _verify_signature(request):
    secret = getattr(settings, 'JIRA_WEBHOOK_SECRET', None)
    if not secret:
        return True

    signature_header = request.headers.get('X-Hub-Signature', '')
    if not signature_header.startswith('sha256='):
        logger.warning('jira_webhook_missing_signature')
        return False

    expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
    received = signature_header[len('sha256='):]
    return hmac.compare_digest(expected, received)


@csrf_exempt
def webhook(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    logger.info('jira_webhook_post_received', extra={
        'content_length': request.headers.get('Content-Length', '?'),
        'has_signature': bool(request.headers.get('X-Hub-Signature')),
        'remote_addr': request.META.get('REMOTE_ADDR', '?'),
    })

    if not _verify_signature(request):
        logger.warning('jira_webhook_invalid_signature')
        return HttpResponse(status=403)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        logger.warning('jira_webhook_invalid_json', extra={'body': request.body[:200]})
        return HttpResponse(status=400)

    event_type = payload.get('webhookEvent', '')
    issue = payload.get('issue', {})

    logger.info('jira_webhook_payload_parsed', extra={
        'event_type': event_type,
        'issue_key': issue.get('key', '—') if issue else '—',
        'has_issue': bool(issue),
    })

    if not issue:
        return HttpResponse(status=200)

    issue_key = issue.get('key', '')
    if not issue_key:
        return HttpResponse(status=200)

    fields = issue.get('fields', {})
    title = fields.get('summary', '')
    project_key = fields.get('project', {}).get('key', '') if fields.get('project') else ''
    issue_type = fields.get('issuetype', {}).get('name', '') if fields.get('issuetype') else ''
    status = fields.get('status', {}).get('name', '') if fields.get('status') else ''
    assignee_obj = fields.get('assignee') or {}
    assignee = assignee_obj.get('displayName', '')
    labels = [l for l in (fields.get('labels') or []) if isinstance(l, str)]
    parent_key = (fields.get('parent') or {}).get('key', '')

    ticket, created = JiraTicket.objects.update_or_create(
        issue_key=issue_key,
        defaults={
            'title': title[:500],
            'project_key': project_key[:50],
            'issue_type': issue_type[:100],
            'status': status[:100],
            'assignee': assignee[:200],
            'labels': labels,
            'parent_key': parent_key[:50],
        },
    )

    summary = _build_summary(event_type, payload)

    JiraEvent.objects.create(
        ticket=ticket,
        event_type=event_type,
        summary=summary,
        payload=payload,
    )

    logger.info(
        'jira_webhook_received',
        extra={'issue_key': issue_key, 'event_type': event_type, 'is_new': created},
    )

    from automations.dispatcher import dispatch
    dispatch(source='jira', payload=payload)

    return HttpResponse(status=200)


def _build_summary(event_type, payload):
    items = payload.get('changelog', {}).get('items', [])
    if items:
        parts = []
        for item in items:
            field = item.get('field', '')
            from_str = item.get('fromString', '')
            to_str = item.get('toString', '')
            if from_str and to_str:
                parts.append(f"{field}: {from_str} → {to_str}")
            elif to_str:
                parts.append(f"{field} set to {to_str}")
        if parts:
            result = '; '.join(parts)
            return result[:497] + '...' if len(result) > 500 else result

    comment = payload.get('comment', {})
    if comment:
        author = comment.get('author', {}).get('displayName', '')
        summary = f"Comment by {author}" if author else 'Comment added'
        return summary[:497] + '...' if len(summary) > 500 else summary

    return event_type.replace('jira:', '').replace('_', ' ').title()[:500]


@login_required
def toggle_deleted(request, issue_key):
    if not request.user.is_staff:
        raise PermissionDenied
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    ticket = get_object_or_404(JiraTicket, issue_key=issue_key)
    ticket.is_deleted = not ticket.is_deleted
    ticket.save(update_fields=['is_deleted'])
    return redirect(reverse('jira-ticket-detail', args=[issue_key]))


@login_required
def resend_event(request, issue_key, event_pk):
    if not request.user.is_staff:
        raise PermissionDenied
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    ticket = get_object_or_404(JiraTicket, issue_key=issue_key)
    event = get_object_or_404(JiraEvent, pk=event_pk, ticket=ticket)
    from automations.dispatcher import dispatch
    dispatch(source='jira', payload=event.payload)
    return redirect(reverse('jira-ticket-detail', args=[issue_key]))


@login_required
def open_in_sandbox(request, issue_key, event_pk):
    if not request.user.is_staff:
        raise PermissionDenied
    ticket = get_object_or_404(JiraTicket, issue_key=issue_key)
    event = get_object_or_404(JiraEvent, pk=event_pk, ticket=ticket)
    request.session['sandbox_payload'] = json.dumps(event.payload, indent=2)
    return redirect(reverse('sandbox') + '?back=1')


@login_required
def ticket_list(request):
    last_event_pk = JiraEvent.objects.filter(
        ticket=OuterRef('pk')
    ).order_by('-received_at').values('pk')[:1]

    all_tickets = JiraTicket.objects.annotate(last_event_pk=Subquery(last_event_pk))

    all_labels = sorted({
        label
        for ticket in JiraTicket.objects.only('labels')
        for label in (ticket.labels or [])
    })

    all_statuses = sorted(
        JiraTicket.objects.exclude(is_deleted=True).values_list('status', flat=True).distinct()
    )

    selected_labels = request.GET.getlist('labels')
    selected_statuses = request.GET.getlist('statuses')
    tickets = all_tickets
    for label in selected_labels:
        tickets = tickets.filter(labels__contains=[label])
    if selected_statuses:
        tickets = tickets.filter(status__in=selected_statuses)

    return render(request, 'jira_integration/ticket_list.html', {
        'tickets': tickets,
        'all_labels': all_labels,
        'selected_labels': selected_labels,
        'all_statuses': all_statuses,
        'selected_statuses': selected_statuses,
    })


def _format_duration(delta):
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return '—'
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _build_status_timeline(ticket, events):
    from django.utils import timezone
    transitions = []
    for event in sorted(events, key=lambda e: e.received_at):
        items = event.payload.get('changelog', {}).get('items', [])
        for item in items:
            if item.get('field') == 'status':
                transitions.append({
                    'from_status': item.get('fromString', ''),
                    'to_status': item.get('toString', ''),
                    'at': event.received_at,
                })

    if not transitions:
        return []

    timeline = []
    first = transitions[0]
    timeline.append({'status': first['from_status'], 'entered_at': None, 'exited_at': first['at']})
    for i, t in enumerate(transitions):
        exited_at = transitions[i + 1]['at'] if i + 1 < len(transitions) else None
        timeline.append({'status': t['to_status'], 'entered_at': t['at'], 'exited_at': exited_at})

    now = timezone.now()
    for entry in timeline:
        if entry['entered_at'] and entry['exited_at']:
            entry['duration'] = _format_duration(entry['exited_at'] - entry['entered_at'])
            entry['ongoing'] = False
        elif entry['entered_at'] and not entry['exited_at']:
            entry['duration'] = _format_duration(now - entry['entered_at'])
            entry['ongoing'] = True
        else:
            entry['duration'] = '—'
            entry['ongoing'] = False

    return list(reversed(timeline))


@login_required
def ticket_detail(request, issue_key):
    ticket = get_object_or_404(JiraTicket, issue_key=issue_key)
    events = list(ticket.events.order_by('-received_at'))

    for event in events:
        event.payload_pretty = json.dumps(event.payload, indent=2)

    last_event = events[0] if events else None
    status_timeline = _build_status_timeline(ticket, events)

    from timetracking.models import TimeEntry
    my_entries = TimeEntry.objects.filter(
        user=request.user, jira_ticket=ticket
    ).order_by('-date', '-created_at')

    # Parent
    parent_data = None
    if ticket.parent_key:
        parent_obj = JiraTicket.objects.filter(issue_key=ticket.parent_key).first()
        if parent_obj:
            parent_data = {
                'ticket': parent_obj,
                'issue_key': parent_obj.issue_key,
                'title': parent_obj.title,
                'status': parent_obj.status,
                'issue_type': parent_obj.issue_type,
            }
        else:
            raw = {}
            if last_event:
                raw = (last_event.payload.get('issue') or {}).get('fields', {}).get('parent') or {}
            parent_data = {
                'ticket': None,
                'issue_key': ticket.parent_key,
                'title': (raw.get('fields') or {}).get('summary', ''),
                'status': ((raw.get('fields') or {}).get('status') or {}).get('name', ''),
                'issue_type': ((raw.get('fields') or {}).get('issuetype') or {}).get('name', ''),
            }

    # Children
    children_in_db = list(JiraTicket.objects.filter(parent_key=ticket.issue_key))
    children_in_db_keys = {c.issue_key for c in children_in_db}
    children = [
        {'ticket': c, 'issue_key': c.issue_key, 'title': c.title,
         'status': c.status, 'issue_type': c.issue_type}
        for c in children_in_db
    ]
    if last_event:
        for sub in (last_event.payload.get('issue') or {}).get('fields', {}).get('subtasks') or []:
            key = sub.get('key', '')
            if key and key not in children_in_db_keys:
                f = sub.get('fields') or {}
                children.append({
                    'ticket': None,
                    'issue_key': key,
                    'title': f.get('summary', ''),
                    'status': (f.get('status') or {}).get('name', ''),
                    'issue_type': (f.get('issuetype') or {}).get('name', ''),
                })

    return render(request, 'jira_integration/ticket_detail.html', {
        'ticket': ticket,
        'events': events,
        'last_event': last_event,
        'status_timeline': status_timeline,
        'my_time_entries': my_entries,
        'parent_data': parent_data,
        'children': children,
    })
