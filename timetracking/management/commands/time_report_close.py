import datetime as dt
import logging
import zoneinfo

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django_mongodb_backend import transaction
from django.http import QueryDict
from django.utils import timezone

from notes.models import Note
from settings_hub.models import AppSetting
from timetracking import auto_reports
from timetracking.models import GeneratedTimeReport, WorkSchedule
from timetracking.tag_report_views import _Report, build_prompt_text

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Create the private personal Time Report notes (Personal / Jira Time Report / YYYY / MM) for the '
        'weeks, months and N-day periods that have closed, as enabled in Settings -> Time Report. '
        'Idempotent: periods already handled (even if the note was deleted) are skipped. Run daily from host cron.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--backfill', type=int, default=1, help='Create the last N closed periods per kind (default 1).')
        parser.add_argument('--dry-run', action='store_true', help='List what would be created; write nothing.')
        parser.add_argument('--user', help='Only this username.')
        parser.add_argument('--today', help='Treat this local date (YYYY-MM-DD) as today.')

    def handle(self, *args, **options):
        settings = auto_reports.load_settings()
        if not (settings['weekly'] or settings['monthly'] or settings['other']):
            self.stdout.write('Auto report creation is off in Settings; nothing to do.')
            return
        backfill = max(1, options['backfill'])
        today_override = dt.date.fromisoformat(options['today']) if options['today'] else None

        users = User.objects.filter(is_active=True).order_by('username')
        if options['user']:
            users = users.filter(username=options['user'])
        totals = {'created': 0, 'empty': 0, 'skipped': 0}
        for user in users:
            try:
                result = self._run_user(user, settings, backfill, today_override, options['dry_run'])
            except Exception:
                logger.exception('time_report_close_user_failed', extra={'user': user.username})
                self.stderr.write(f'{user.username}: failed; see log.')
                continue
            for key, value in result.items():
                totals[key] += value
        if not options['dry_run']:
            AppSetting.objects.update_or_create(
                key=auto_reports.LAST_RUN_KEY, defaults={'value': timezone.now().isoformat(timespec='seconds')},
            )
        self.stdout.write(
            f"{'Would create' if options['dry_run'] else 'Created'} {totals['created']} note(s); "
            f"{totals['empty']} empty period(s) recorded; {totals['skipped']} already handled."
        )

    def _run_user(self, user, settings, backfill, today_override, dry_run):
        result = {'created': 0, 'empty': 0, 'skipped': 0}
        try:
            jira_account_id = user.userprofile.jira_account_id.strip()
        except Exception:
            jira_account_id = ''
        schedule = WorkSchedule.objects.filter(user=user).first()
        jira_username = schedule.jira_username.strip() if schedule and schedule.jira_username else ''
        if not (jira_account_id or jira_username):
            return result
        try:
            tz = zoneinfo.ZoneInfo(schedule.timezone) if schedule and schedule.timezone else dt.timezone.utc
        except Exception:
            tz = dt.timezone.utc
        today = today_override or timezone.now().astimezone(tz).date()

        for period in auto_reports.periods_for(settings, today, backfill):
            if GeneratedTimeReport.objects.filter(user=user, file_id=period['id']).exists():
                result['skipped'] += 1
                continue
            if dry_run:
                self.stdout.write(f"{user.username}: would handle {period['id']} ({period['start']} - {period['end']})")
                result['created'] += 1
                continue
            params = QueryDict(mutable=True)
            params.update({'range': 'custom', 'date_from': period['start'].isoformat(), 'date_to': period['end'].isoformat()})
            report = _Report(user, params, with_descriptions=True)
            with transaction.atomic():
                record = GeneratedTimeReport(
                    user=user, file_id=period['id'], kind=period['kind'],
                    period_start=period['start'], period_end=period['end'],
                )
                if not report.totals['tickets']:
                    record.empty = True
                    record.save()
                    result['empty'] += 1
                    continue
                notebook = auto_reports.ensure_folder(user, period['start'])
                Note.objects.get_or_create(
                    notebook=notebook, file_id=period['id'],
                    defaults={'title': auto_reports.title_for(period), 'body': build_prompt_text(report), 'owner': user},
                )
                record.save()
            result['created'] += 1
            self.stdout.write(f"{user.username}: created {period['id']}")
        return result
