import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from notifications.models import NotificationRule
from notifications.rules import notifications_enabled, run_rule

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Evaluate every active notification rule against Jira tickets and notify recipients '
        'once per (rule, ticket). Safe to run every few minutes from host cron.'
    )

    def handle(self, *args, **options):
        if not notifications_enabled():
            self.stdout.write('Notifications are disabled system-wide; nothing evaluated.')
            return

        now = timezone.now()
        for rule in NotificationRule.objects.filter(is_active=True):
            try:
                count = run_rule(rule, now)
            except Exception:
                logger.exception('jira_rules_check_rule_failed', extra={'rule_id': rule.pk})
                self.stderr.write(f'Rule "{rule.name}" failed; see log.')
                continue
            logger.info('jira_rules_check_rule_done', extra={'rule_id': rule.pk, 'notified': count})
            self.stdout.write(f'Rule "{rule.name}": {count} notified.')
