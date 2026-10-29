import logging
import re
from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone

from automations.evaluator import evaluate_filter
from core.models import UserProfile
from settings_hub.models import get_app_setting

from .models import ENABLED_KEY, NotificationRuleHit, notify

logger = logging.getLogger(__name__)

SOURCE = 'jira_rule'
MAX_NOTIFICATIONS_PER_RUN = 50

SUPPORTED_OPS = {
    'eq', 'neq', 'eq_ci', 'in', 'not_in', 'in_ci', 'not_in_ci', 'contains', 'exists', 'regex',
}
LIST_OPS = {'in', 'not_in', 'in_ci', 'not_in_ci'}

DEFAULT_FILTER = {
    'and': [
        {'path': '$.issue.fields.project.key', 'op': 'eq', 'value': 'GITIN'},
        {'path': '$.issue.fields.labels', 'op': 'not_in_ci', 'value': ['INFRADEVOPS']},
    ]
}
DEFAULT_MESSAGE = 'Untagged ticket {key}: {title}'
PLACEHOLDERS = ('key', 'title', 'project', 'status')


def validate_filter(condition, _depth=0):
    """Return an error string for a malformed or unsupported filter tree, or None if valid.
    evaluate_filter() silently returns False on bad input, so this runs on save."""
    if _depth == 0 and not condition:
        return 'The rule must not be empty.'
    if not isinstance(condition, dict):
        return 'Every node must be a JSON object.'
    if 'and' in condition or 'or' in condition:
        key = 'and' if 'and' in condition else 'or'
        children = condition[key]
        if not isinstance(children, list) or not children:
            return f'"{key}" must be a non-empty list.'
        for child in children:
            error = validate_filter(child, _depth + 1)
            if error:
                return error
        return None
    path = condition.get('path')
    op = condition.get('op')
    if not isinstance(path, str) or not path.startswith('$'):
        return 'Every condition needs a "path" starting with "$".'
    if op not in SUPPORTED_OPS:
        return f'Unsupported op {op!r}. Supported: {", ".join(sorted(SUPPORTED_OPS))}.'
    if op == 'exists':
        return None
    if 'value' not in condition:
        return f'Op "{op}" needs a "value".'
    if op in LIST_OPS and not isinstance(condition['value'], list):
        return f'Op "{op}" needs a list "value".'
    if op == 'regex':
        try:
            re.compile(condition['value'])
        except (re.error, TypeError):
            return 'Invalid regex pattern.'
    return None


def validate_message(message):
    try:
        message.format_map({p: '' for p in PLACEHOLDERS})
    except (KeyError, IndexError, ValueError):
        return f'Invalid placeholder. Use only: {", ".join("{" + p + "}" for p in PLACEHOLDERS)}.'
    return None


def build_payload(ticket):
    """Jira-shaped payload rebuilt from the current JiraTicket (never the stale issue_created one)."""
    return {
        'issue': {
            'key': ticket.issue_key,
            'fields': {
                'project': {'key': ticket.project_key},
                'labels': list(ticket.labels or []),
                'status': {'name': ticket.status},
                'summary': ticket.title,
                'assignee': {'accountId': ticket.assignee_account_id, 'displayName': ticket.assignee},
            },
        }
    }


def ticket_matches(condition, ticket):
    return evaluate_filter(condition, build_payload(ticket))


def render_message(rule, ticket):
    values = {
        'key': ticket.issue_key,
        'title': ticket.title,
        'project': ticket.project_key,
        'status': ticket.status,
    }
    try:
        return rule.message.format_map(values)[:500]
    except (KeyError, IndexError, ValueError):
        return rule.message[:500]


def ticket_url(ticket):
    base = get_app_setting('jira_base_url', '').rstrip('/')
    if base:
        return f'{base}/browse/{ticket.issue_key}'
    return f'/time/report/ticket/{ticket.issue_key}/timeline/'


def rule_recipients(rule, ticket):
    recipients = set(rule.users.all())
    team_ids = list(rule.teams.values_list('pk', flat=True))
    if team_ids:
        recipients |= set(User.objects.filter(vault_teams__pk__in=team_ids))
    if rule.notify_assignee and ticket.assignee_account_id:
        profile = (
            UserProfile.objects.filter(jira_account_id=ticket.assignee_account_id)
            .select_related('user').first()
        )
        if profile:
            recipients.add(profile.user)
    return recipients


def eligible_tickets(rule, now):
    from jira_integration.models import JiraTicket

    return (
        JiraTicket.objects.filter(
            is_deleted=False,
            created_at__gt=rule.starts_at,
            created_at__lte=now - timedelta(minutes=rule.grace_minutes),
        )
        .exclude(issue_key__in=NotificationRuleHit.objects.filter(rule=rule).values('issue_key'))
        .order_by('created_at')
    )


def run_rule(rule, now=None):
    """Evaluate one rule and notify for every newly matching ticket. Returns the number notified."""
    now = now or timezone.now()
    notified = 0
    for ticket in eligible_tickets(rule, now):
        if notified >= MAX_NOTIFICATIONS_PER_RUN:
            break
        if not ticket_matches(rule.filter, ticket):
            continue
        recipients = rule_recipients(rule, ticket)
        if not recipients:
            continue
        created = notify(
            render_message(rule, ticket), url=ticket_url(ticket), source=SOURCE, users=recipients,
        )
        if created:
            NotificationRuleHit.objects.get_or_create(rule=rule, issue_key=ticket.issue_key)
            notified += 1
    return notified


def notifications_enabled():
    return get_app_setting(ENABLED_KEY, 'True') == 'True'
