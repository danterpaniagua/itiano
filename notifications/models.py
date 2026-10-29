from django.contrib.auth.models import User
from django.db import models

ENABLED_KEY = 'notifications_enabled'


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.CharField(max_length=500)
    url = models.CharField(max_length=500, blank=True)
    source = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} — {self.message}'


def notify(message, *, url='', source='', users=None, team=None):
    """Create a Notification for a single user, an iterable of users, or every
    current member of a core.Team (membership resolved now — a later change to
    team membership never retroactively adds/removes recipients of this call).

    Exactly one of `users`/`team` must be given. `users=[]` (or a team with no
    members) is a valid no-op, distinct from omitting both.

    Gated by the system-wide AppSetting `notifications_enabled` (default on) —
    when disabled, this is a no-op for every caller, checked here so no
    individual trigger needs its own copy of that check. Argument validation
    still runs first, so a caller bug is not silently masked by the toggle.
    """
    if (users is None) == (team is None):
        raise ValueError('notify() requires exactly one of users or team')

    from settings_hub.models import get_app_setting
    if get_app_setting(ENABLED_KEY, 'True') != 'True':
        return []

    if team is not None:
        recipients = list(team.members.all())
    elif isinstance(users, User):
        recipients = [users]
    else:
        recipients = list(users)

    if not recipients:
        return []

    return Notification.objects.bulk_create([
        Notification(user=recipient, message=message[:500], url=url, source=source)
        for recipient in recipients
    ])


class NotificationRule(models.Model):
    """A JSON query over Jira tickets that alerts its recipients when a ticket matches
    (evaluated delayed and periodically by the `jira_rules_check` command). Only tickets
    created after `starts_at` are ever considered, so a new rule never alerts retroactively."""

    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    filter = models.JSONField(
        help_text='Condition tree evaluated against a payload rebuilt from the current JiraTicket.'
    )
    grace_minutes = models.PositiveIntegerField(default=15)
    message = models.CharField(max_length=500)
    notify_assignee = models.BooleanField(default=False)
    users = models.ManyToManyField(User, blank=True, related_name='notification_rules')
    teams = models.ManyToManyField('core.Team', blank=True, related_name='notification_rules')
    starts_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class NotificationRuleHit(models.Model):
    """One row per (rule, ticket) already notified — guarantees a single alert."""

    rule = models.ForeignKey(NotificationRule, on_delete=models.CASCADE, related_name='hits')
    issue_key = models.CharField(max_length=50)
    notified_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('rule', 'issue_key')]

    def __str__(self):
        return f'{self.rule} — {self.issue_key}'
