"""Tag time report page and its prompt export (v5.21.0): /time/report/."""
import datetime as dt
import zoneinfo

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from jira_integration.event_data import events_for
from jira_integration.models import JiraTicket
from notes import system_prompts
from settings_hub.models import get_app_setting, JiraStatusConfig

from . import tag_report
from .map_views import format_map_date, resolve_range
from .models import WorkSchedule


def _created_at(payload):
    value = ((payload.get('issue') or {}).get('fields') or {}).get('created')
    if not value:
        return None
    try:
        moment = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)


class _Report:
    """Everything both endpoints need: filters, the viewer's tickets and the computed sections."""

    def __init__(self, user, params, with_descriptions=False, now=None):
        """`params` is a QueryDict-like (`range`, `date_from`, `date_to`, `tags`): the request's GET for the pages,
        a built one for the management command (v5.22.0)."""
        schedule, _ = WorkSchedule.objects.get_or_create(user=user)
        self.schedule = schedule
        jira_username = schedule.jira_username.strip() if schedule.jira_username else ''
        try:
            jira_account_id = user.userprofile.jira_account_id.strip()
        except Exception:
            jira_account_id = ''
        self.jira_account_id, self.jira_username = jira_account_id, jira_username
        try:
            self.tz = zoneinfo.ZoneInfo(schedule.timezone) if schedule.timezone else dt.timezone.utc
        except Exception:
            self.tz = dt.timezone.utc

        self.now = now or timezone.now()
        (self.range_param, self.start, self.end,
         self.from_text, self.to_text, self.range_error) = resolve_range(params, self.tz, self.now)
        self.selected_tags = [t for t in params.getlist('tags') if t]
        self.default_tags = tag_report.default_tags()
        self.tags = self.selected_tags or self.default_tags

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
        self.tickets = tickets
        self.all_tags = sorted({label for t in tickets for label in (t.labels or [])})

        transitions = {t.issue_key: [] for t in tickets}
        created = {}
        self.descriptions = {}
        key_of = {t.pk: t.issue_key for t in tickets}
        event_paths = ['changelog__items', 'issue__fields__created']
        if with_descriptions:
            event_paths.append('issue__fields__description')
        for event in events_for(key_of, event_paths):
            key = key_of[event.ticket_id]
            for item in event.payload.get('changelog', {}).get('items', []):
                if item.get('field') == 'status':
                    transitions[key].append({
                        'from_status': item.get('fromString', ''),
                        'to_status': item.get('toString', ''),
                        'at': event.received_at,
                    })
            if key not in created:
                moment = _created_at(event.payload)
                if moment:
                    created[key] = moment
            if with_descriptions:
                description = ((event.payload.get('issue') or {}).get('fields') or {}).get('description')
                if description:
                    self.descriptions[key] = description   # ascending order: the latest one wins

        rows = tag_report.build_rows(
            tickets, transitions, categories, schedule, self.tz, self.start, self.end, self.now, created,
        )
        tag_report.decorate(rows)
        self.rows = rows
        self.sections, self.totals = tag_report.build_sections(rows, self.tags)

    @property
    def range_text(self):
        return f'{format_map_date(self.start.astimezone(self.tz).date())} - {format_map_date(self.end.astimezone(self.tz).date())}'


def build_prompt_text(report):
    """The prompt for a computed report, from the `prompt_time_report` system prompt."""
    return tag_report.build_prompt(
        system_prompts.get_prompt(tag_report.PROMPT_ID), report.tags, report.range_text,
        report.sections, report.descriptions, report.tz,
    )


class TimeReportView(LoginRequiredMixin, View):
    def get(self, request):
        report = _Report(request.user, request.GET)
        return render(request, 'timetracking/tag_report.html', {
            'jira_account_id': report.jira_account_id, 'jira_username': report.jira_username,
            'range_param': report.range_param, 'date_from_text': report.from_text,
            'date_to_text': report.to_text, 'range_error': report.range_error,
            'selected_tags': report.selected_tags, 'default_tags': report.default_tags,
            'all_tags': report.all_tags, 'sections': report.sections, 'totals': report.totals,
            'jira_base_url': get_app_setting('jira_base_url', '').rstrip('/'),
            'range_start': report.start.astimezone(report.tz), 'range_end': report.end.astimezone(report.tz),
        })


class TimeReportPromptView(LoginRequiredMixin, View):
    """The AI prompt for the report currently on screen (same query string), built from the
    `prompt_time_report` system prompt. Only copied by the user; nothing is sent anywhere."""
    def get(self, request):
        report = _Report(request.user, request.GET, with_descriptions=True)
        return JsonResponse({'prompt': build_prompt_text(report)})
