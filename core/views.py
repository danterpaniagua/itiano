from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from automations.models import Trigger
from itsm.models import Ticket
from jira_integration.models import JiraTicket


@login_required
def docs(request):
    return render(request, 'core/docs.html')


@login_required
def dashboard(request):
    import datetime
    from vault.models import Credential
    from notes.models import Note
    from contacts.models import Contact
    from timetracking.models import TimeEntry
    itsm_count = Ticket.objects.exclude(state__in=['closed', 'cancelled']).count()
    jira_count = JiraTicket.objects.count()
    automations_count = Trigger.objects.filter(is_active=True).count()
    vault_count = Credential.objects.filter(owner=request.user).count() if request.user.is_authenticated else 0
    notes_count = Note.objects.filter(owner=request.user).count() if request.user.is_authenticated else 0
    contacts_count = Contact.objects.count() if request.user.is_staff else 0
    from django.utils import timezone as dj_tz
    from jira_integration.models import JiraEvent
    from timetracking.models import WorkSchedule
    import zoneinfo as _zi
    import datetime as _dt

    from core.models import UserProfile
    schedule = WorkSchedule.objects.filter(user=request.user).first()
    jira_username = schedule.jira_username.strip() if schedule and schedule.jira_username else ''
    try:
        jira_account_id = request.user.userprofile.jira_account_id.strip()
    except Exception:
        jira_account_id = ''

    today_ip_hours = 0.0
    weekly_ip_hours = 0.0

    if jira_account_id or jira_username:
        now = dj_tz.now()
        try:
            user_tz = _zi.ZoneInfo(schedule.timezone) if schedule and schedule.timezone else _dt.timezone.utc
        except Exception:
            user_tz = _dt.timezone.utc
        now_local = now.astimezone(user_tz)
        today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(_dt.timezone.utc)
        week_start = (now_local - _dt.timedelta(days=now_local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(_dt.timezone.utc)

        def range_secs(entered, exited, range_start, is_ongoing):
            # Mirrors DailyReportView.range_seconds logic:
            # - segments that started within the range count normally
            # - ongoing In Progress that started before the range counts from range_start
            if not entered:
                return 0
            if entered >= range_start:
                return max(0, int((min(exited or now, now) - entered).total_seconds()))
            if is_ongoing:
                return max(0, int((now - range_start).total_seconds()))
            return 0

        today_secs = 0
        weekly_secs = 0

        qs = JiraTicket.objects.filter(is_deleted=False)
        if jira_account_id:
            qs = qs.filter(assignee_account_id=jira_account_id)
        else:
            qs = qs.filter(assignee__iexact=jira_username)
        for ticket in qs:
            events = list(JiraEvent.objects.filter(ticket=ticket).order_by('received_at'))
            transitions = []
            for event in events:
                for item in event.payload.get('changelog', {}).get('items', []):
                    if item.get('field') == 'status':
                        transitions.append({'to_status': item.get('toString', ''), 'at': event.received_at})
            for i, t in enumerate(transitions):
                if t['to_status'].lower() != 'in progress':
                    continue
                entered = t['at']
                exited = transitions[i + 1]['at'] if i + 1 < len(transitions) else None
                is_ongoing = exited is None
                today_secs += range_secs(entered, exited, today_start, is_ongoing)
                weekly_secs += range_secs(entered, exited, week_start, is_ongoing)

        today_ip_hours = today_secs / 3600
        weekly_ip_hours = weekly_secs / 3600

    return render(request, 'core/dashboard.html', {
        'itsm_count': itsm_count,
        'jira_count': jira_count,
        'automations_count': automations_count,
        'vault_count': vault_count,
        'notes_count': notes_count,
        'contacts_count': contacts_count,
        'today_ip_hours': today_ip_hours,
        'weekly_ip_hours': weekly_ip_hours,
        'has_jira_username': bool(jira_account_id or jira_username),
    })


@login_required
def profile(request):
    contact = getattr(request.user, 'contact', None)
    return render(request, 'core/profile.html', {'contact': contact})


def health(request):
    try:
        from django.db import connection
        connection.ensure_connection()
        return JsonResponse({'status': 'ok'})
    except Exception:
        return JsonResponse({'status': 'error'}, status=503)
