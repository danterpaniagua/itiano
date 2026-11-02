"""In Progress map page (v5.18.4): /time/map/."""
import datetime as dt
import re
import zoneinfo
from functools import partial

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from jira_integration.models import JiraEvent, JiraTicket
from settings_hub.models import get_app_setting, JiraStatusConfig

from . import focus_map, ip_map
from .models import WorkSchedule

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
_DATE_RE = re.compile(r'^(\d{1,2})/([A-Za-z]{3})/(\d{4})$')


def parse_map_date(text):
    """`dd/mmm/yyyy` (English month abbreviation) or ISO `yyyy-mm-dd`; None when invalid."""
    text = (text or '').strip()
    match = _DATE_RE.match(text)
    if match:
        month = match.group(2).capitalize()
        if month not in MONTHS:
            return None
        try:
            return dt.date(int(match.group(3)), MONTHS.index(month) + 1, int(match.group(1)))
        except ValueError:
            return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def format_map_date(day):
    return f'{day.day:02d}/{MONTHS[day.month - 1]}/{day.year}'


def resolve_range(params, tz, now):
    """-> (range_param, start_dt, end_dt, from_text, to_text, error). Same windows as the report."""
    now_local = now.astimezone(tz)
    range_param = params.get('range', 'week')
    if range_param not in ('today', 'week', 'month', 'custom'):
        range_param = 'week'
    from_text = to_text = error = ''

    def midnight(local_dt):
        return local_dt.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt.timezone.utc)

    if range_param == 'custom':
        date_from = parse_map_date(params.get('date_from', ''))
        date_to = parse_map_date(params.get('date_to', ''))
        if date_from is None or date_to is None or date_to < date_from:
            error = 'Enter a valid range as dd/mmm/yyyy (for example 23/Oct/2026), From before To.'
            range_param = 'week'
        else:
            from_text, to_text = format_map_date(date_from), format_map_date(date_to)
            start_dt = dt.datetime(date_from.year, date_from.month, date_from.day, tzinfo=tz).astimezone(dt.timezone.utc)
            end_dt = dt.datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=tz).astimezone(dt.timezone.utc)
            return range_param, start_dt, min(end_dt, now), from_text, to_text, error
    if range_param == 'today':
        start_dt = midnight(now_local)
    elif range_param == 'week':
        start_dt = midnight(now_local - dt.timedelta(days=7))
    else:
        start_dt = midnight(now_local - dt.timedelta(days=30))
    return range_param, start_dt, now, from_text, to_text, error


class TimeMapView(LoginRequiredMixin, View):
    def get(self, request):
        schedule, _ = WorkSchedule.objects.get_or_create(user=request.user)
        jira_username = schedule.jira_username.strip() if schedule.jira_username else ''
        try:
            jira_account_id = request.user.userprofile.jira_account_id.strip()
        except Exception:
            jira_account_id = ''
        try:
            tz = zoneinfo.ZoneInfo(schedule.timezone) if schedule.timezone else dt.timezone.utc
        except Exception:
            tz = dt.timezone.utc

        now = timezone.now()
        range_param, start_dt, end_dt, from_text, to_text, range_error = resolve_range(request.GET, tz, now)
        view_mode = 'overlap' if request.GET.get('time') == 'overlap' else 'exclusive'
        selected_tags = [t for t in request.GET.getlist('tags') if t]

        configs = list(JiraStatusConfig.objects.all())
        categories = (
            {c.status_name.lower(): c.category for c in configs}
            if configs else {'in progress': 'in_progress', 'done': 'done', 'descartado': 'done'}
        )

        tickets = []
        if jira_account_id or jira_username:
            qs = JiraTicket.objects.filter(is_deleted=False)
            qs = qs.filter(assignee_account_id=jira_account_id) if jira_account_id else qs.filter(assignee__iexact=jira_username)
            tickets = list(qs.order_by('issue_key'))

        transitions = {t.issue_key: [] for t in tickets}
        key_of = {t.pk: t.issue_key for t in tickets}
        for event in JiraEvent.objects.filter(ticket_id__in=list(key_of)).order_by('received_at'):
            for item in event.payload.get('changelog', {}).get('items', []):
                if item.get('field') == 'status':
                    transitions[key_of[event.ticket_id]].append({
                        'from_status': item.get('fromString', ''),
                        'to_status': item.get('toString', ''),
                        'at': event.received_at,
                    })

        all_tags = sorted({label for t in tickets for label in (t.labels or [])})
        visible_keys = None
        if selected_tags:
            visible_keys = {
                t.issue_key for t in tickets
                if all(tag in (t.labels or []) for tag in selected_tags)
            }

        working = partial(focus_map.working_seconds, schedule, tz)
        context = {
            'jira_account_id': jira_account_id, 'jira_username': jira_username,
            'range_param': range_param, 'date_from_text': from_text, 'date_to_text': to_text,
            'range_error': range_error, 'view_mode': view_mode,
            'selected_tags': selected_tags, 'all_tags': all_tags, 'selected_statuses': [],
            'jira_base_url': get_app_setting('jira_base_url', '').rstrip('/'),
            'range_start': start_dt.astimezone(tz), 'range_end': end_dt.astimezone(tz),
        }
        if view_mode == 'exclusive':
            parent_keys = {t.parent_key for t in tickets if t.parent_key}
            mine = {t.issue_key for t in tickets}
            parent_titles = dict(
                JiraTicket.objects.filter(issue_key__in=parent_keys - mine).values_list('issue_key', 'title')
            ) if parent_keys - mine else {}
            subs_total = {
                row['parent_key']: row['n']
                for row in JiraTicket.objects.filter(parent_key__in=parent_keys, is_deleted=False)
                .values('parent_key').annotate(n=Count('id'))
            } if parent_keys else {}
            data = focus_map.build_focus_map(
                tickets, transitions, categories, schedule, tz, start_dt, end_dt, now,
                visible_keys=visible_keys, parent_titles=parent_titles, subs_total=subs_total,
            )
            context.update({'focus_days': data['days'], 'focus_alert': data['alert'], 'focus_summary': data['summary']})
        else:
            data = ip_map.build_ip_map(
                tickets, transitions, categories, start_dt, end_dt, tz,
                visible_keys=visible_keys,
                working_seconds=working if schedule.start_time and schedule.end_time else None,
            )
            context.update({
                'ip_map_days': data['days'], 'ip_map_summary': data['summary'],
                'ip_map_has_wh': data['has_wh'], 'ip_map_mermaid': data['mermaid'],
            })
        return render(request, 'timetracking/map.html', context)
