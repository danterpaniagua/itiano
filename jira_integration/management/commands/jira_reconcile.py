import logging
import time
from datetime import timedelta

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Max
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from jira_integration.models import JiraEvent, JiraTicket
from jira_integration.views import _build_summary
from settings_hub.models import AppSetting, get_app_setting

logger = logging.getLogger(__name__)

WATERMARK_KEY = 'jira_reconcile_watermark'
PROJECTS_KEY = 'jira_reconcile_projects'
DEFAULT_PROJECTS = 'GITIN'
DEFAULT_LOOKBACK_HOURS = 24
PAGE_SIZE = 100
RATE_LIMIT_RETRIES = 3


class Command(BaseCommand):
    help = (
        'Reconcile Jira status history by polling the Jira API for status transitions '
        'the webhook missed (e.g. while the app was down).'
    )

    def handle(self, *args, **options):
        base_url = getattr(settings, 'JIRA_API_BASE_URL', '').rstrip('/')
        email = getattr(settings, 'JIRA_API_EMAIL', '')
        token = getattr(settings, 'JIRA_API_TOKEN', '')

        if not (base_url and email and token):
            self.stderr.write(
                'JIRA_API_BASE_URL / JIRA_API_EMAIL / JIRA_API_TOKEN are not configured — aborting.'
            )
            return

        run_started_at = timezone.now()
        watermark = self._get_watermark()
        projects = self._get_projects()

        session = requests.Session()
        session.auth = (email, token)
        session.headers['Accept'] = 'application/json'

        stats = {'issues_scanned': 0, 'events_created': 0, 'errors': 0}

        try:
            for issue_key in self._iter_updated_issue_keys(session, base_url, watermark, projects):
                stats['issues_scanned'] += 1
                try:
                    self._reconcile_issue(session, base_url, issue_key, stats)
                except Exception:
                    stats['errors'] += 1
                    logger.exception('jira_reconcile_issue_failed', extra={'issue_key': issue_key})
        except Exception:
            logger.exception('jira_reconcile_run_failed', extra=stats)
            self.stderr.write('Reconciliation run failed before completing — watermark not advanced.')
            return

        if stats['errors'] == 0:
            self._set_watermark(run_started_at)
        else:
            logger.warning('jira_reconcile_partial_run', extra=stats)

        logger.info('jira_reconcile_run_complete', extra={**stats, 'watermark_advanced': stats['errors'] == 0})
        self.stdout.write(
            f"Scanned {stats['issues_scanned']} issues, created {stats['events_created']} events, "
            f"{stats['errors']} errors."
        )

    # -- watermark -----------------------------------------------------

    def _get_watermark(self):
        raw = get_app_setting(WATERMARK_KEY, '')
        parsed = parse_datetime(raw) if raw else None
        if parsed:
            return parsed
        return timezone.now() - timedelta(hours=DEFAULT_LOOKBACK_HOURS)

    def _set_watermark(self, when):
        AppSetting.objects.update_or_create(key=WATERMARK_KEY, defaults={'value': when.isoformat()})

    def _get_projects(self):
        raw = get_app_setting(PROJECTS_KEY, DEFAULT_PROJECTS)
        return [key.strip() for key in raw.split(',') if key.strip()]

    # -- Jira API --------------------------------------------------------

    def _get(self, session, url, params=None):
        for attempt in range(RATE_LIMIT_RETRIES):
            response = session.get(url, params=params, timeout=30)
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', '5'))
                logger.warning(
                    'jira_reconcile_rate_limited',
                    extra={'url': url, 'retry_after': retry_after, 'attempt': attempt},
                )
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            return response
        response.raise_for_status()
        return response

    def _iter_updated_issue_keys(self, session, base_url, since, projects):
        # /rest/api/3/search is deprecated (returns 410 Gone) — use the enhanced
        # /rest/api/3/search/jql endpoint, which paginates via nextPageToken
        # instead of startAt/total.
        jql = f'updated >= "{since.strftime("%Y-%m-%d %H:%M")}"'
        if projects:
            project_list = ', '.join(f'"{key}"' for key in projects)
            jql = f'project in ({project_list}) AND {jql}'
        jql += ' ORDER BY updated ASC'
        next_page_token = None
        while True:
            params = {'jql': jql, 'maxResults': PAGE_SIZE, 'fields': 'key'}
            if next_page_token:
                params['nextPageToken'] = next_page_token
            response = self._get(session, f'{base_url}/rest/api/3/search/jql', params=params)
            data = response.json()
            issues = data.get('issues', [])
            for issue in issues:
                yield issue['key']
            next_page_token = data.get('nextPageToken')
            if not next_page_token or not issues:
                break

    def _iter_changelog(self, session, base_url, issue_key):
        start_at = 0
        while True:
            response = self._get(
                session,
                f'{base_url}/rest/api/3/issue/{issue_key}/changelog',
                params={'startAt': start_at, 'maxResults': PAGE_SIZE},
            )
            data = response.json()
            values = data.get('values', [])
            for history in values:
                yield history
            start_at += len(values)
            if not values or start_at >= data.get('total', 0):
                break

    # -- reconciliation ---------------------------------------------------

    def _reconcile_issue(self, session, base_url, issue_key, stats):
        try:
            ticket = JiraTicket.objects.get(issue_key=issue_key)
        except JiraTicket.DoesNotExist:
            logger.info('jira_reconcile_unknown_ticket_skipped', extra={'issue_key': issue_key})
            return

        status_histories = []
        for history in self._iter_changelog(session, base_url, issue_key):
            status_items = [item for item in history.get('items', []) if item.get('field') == 'status']
            if status_items:
                status_histories.append((history, status_items))

        status_histories.sort(key=lambda pair: pair[0].get('created', ''))

        last_event_at = JiraEvent.objects.filter(ticket=ticket).aggregate(Max('received_at'))['received_at__max']

        created_count = 0
        for history, status_items in status_histories:
            history_id = history.get('id')
            if JiraEvent.objects.filter(ticket=ticket, payload__changelog__id=history_id).exists():
                continue

            created_at = parse_datetime(history.get('created', '')) or timezone.now()

            payload = {
                'webhookEvent': 'jira:issue_updated',
                'issue': {'key': issue_key},
                'changelog': {'id': history_id, 'items': status_items},
                'source': 'jira_reconcile',
            }
            summary = _build_summary('jira:issue_updated', payload)

            JiraEvent.objects.create(
                ticket=ticket,
                event_type='jira:issue_updated',
                summary=summary,
                payload=payload,
                received_at=created_at,
            )
            stats['events_created'] += 1
            created_count += 1

            # Only move JiraTicket.status forward in time, so an older backfilled
            # entry never rolls back a status the live webhook already recorded.
            if last_event_at is None or created_at >= last_event_at:
                new_status = status_items[-1].get('toString', '')
                if new_status:
                    JiraTicket.objects.filter(pk=ticket.pk).update(status=new_status[:100])
                last_event_at = created_at

        logger.info(
            'jira_reconcile_issue_done',
            extra={
                'issue_key': issue_key,
                'outcome': 'updated' if created_count else 'unchanged',
                'events_created': created_count,
            },
        )
