import logging
import time
from datetime import timedelta

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db.models import Max
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.models import Team
from jira_integration.models import JiraEvent, JiraTicket
from jira_integration.views import _build_summary, _ticket_defaults_from_fields
from notifications.models import notify
from settings_hub.models import AppSetting, get_app_setting

logger = logging.getLogger(__name__)

WATERMARK_KEY = 'jira_reconcile_watermark'
PROJECTS_KEY = 'jira_reconcile_projects'
NOTIFY_USERS_KEY = 'jira_reconcile_notify_users'
NOTIFY_TEAM_KEY = 'jira_reconcile_notify_team'
LOOKBACK_HOURS_KEY = 'jira_reconcile_lookback_hours'
LAST_COUNT_KEY = 'jira_reconcile_last_count'
DEFAULT_PROJECTS = 'GITIN'
DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_LAST_COUNT = 300
PAGE_SIZE = 100
RATE_LIMIT_RETRIES = 3


class Command(BaseCommand):
    help = (
        'Reconcile Jira status history by polling the Jira API for status transitions '
        'the webhook missed (e.g. while the app was down).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'mode',
            nargs='?',
            default='by_time',
            choices=['by_time', 'last'],
            help="'by_time' (default): poll Jira for tickets updated since the watermark, "
                 "for the project(s) in AppSetting jira_reconcile_projects — skips tickets "
                 "unknown locally. 'last': backfill the N most recent tickets by issue number "
                 "for the first configured project, creating any missing locally.",
        )
        parser.add_argument(
            'count',
            nargs='?',
            type=int,
            default=None,
            help="With 'last' mode: how many of the most recent tickets to backfill "
                 "(default: AppSetting jira_reconcile_last_count, itself defaulting to "
                 f"{DEFAULT_LAST_COUNT}). Ignored in 'by_time' mode.",
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

        range_mode = options['mode'] == 'last'

        run_started_at = timezone.now()

        session = requests.Session()
        session.auth = (email, token)
        session.headers['Accept'] = 'application/json'

        stats = {
            'issues_scanned': 0,
            'tickets_created': 0,
            'events_created': 0,
            'comments_created': 0,
            'issues_not_found': 0,
            'errors': 0,
        }

        if range_mode:
            projects = self._get_projects()
            if not projects:
                self.stderr.write(
                    "No project configured in AppSetting jira_reconcile_projects — "
                    "cannot determine a 'last' range."
                )
                return
            project = projects[0]
            count = options['count']
            if count is None:
                count = self._get_int_setting(LAST_COUNT_KEY, DEFAULT_LAST_COUNT)
            try:
                highest_num = self._fetch_highest_issue_number(session, base_url, project)
            except requests.HTTPError:
                logger.exception('jira_reconcile_last_lookup_failed', extra={'project': project})
                self.stderr.write(f'Could not determine the latest {project} issue number — aborting.')
                return
            if highest_num is None:
                self.stderr.write(f'No issues found for project {project!r} — nothing to do.')
                return
            start_num = max(1, highest_num - count + 1)
            issue_keys = self._iter_key_range(project, start_num, highest_num)
        else:
            watermark = self._get_watermark()
            projects = self._get_projects()
            issue_keys = self._iter_updated_issue_keys(session, base_url, watermark, projects)

        try:
            for issue_key in issue_keys:
                stats['issues_scanned'] += 1
                try:
                    self._reconcile_issue(session, base_url, issue_key, stats, create_missing=range_mode)
                except Exception:
                    stats['errors'] += 1
                    logger.exception('jira_reconcile_issue_failed', extra={'issue_key': issue_key})
        except Exception:
            logger.exception('jira_reconcile_run_failed', extra=stats)
            self.stderr.write('Reconciliation run failed before completing — watermark not advanced.')
            return

        # A key-range backfill is a one-off operation unrelated to the updated-since
        # cursor, so it must never advance the watermark used by the scheduled run.
        if not range_mode:
            if stats['errors'] == 0:
                self._set_watermark(run_started_at)
            else:
                logger.warning('jira_reconcile_partial_run', extra=stats)

        if stats['issues_scanned'] > 0:
            self._notify_completion(range_mode, stats)

        logger.info(
            'jira_reconcile_run_complete',
            extra={**stats, 'range_mode': range_mode, 'watermark_advanced': not range_mode and stats['errors'] == 0},
        )
        self.stdout.write(
            f"Scanned {stats['issues_scanned']} issues, created {stats['tickets_created']} tickets, "
            f"{stats['events_created']} status events, {stats['comments_created']} comments, "
            f"{stats['issues_not_found']} not found, {stats['errors']} errors."
        )

    # -- watermark -----------------------------------------------------

    def _get_watermark(self):
        raw = get_app_setting(WATERMARK_KEY, '')
        parsed = parse_datetime(raw) if raw else None
        if parsed:
            return parsed
        lookback_hours = self._get_int_setting(LOOKBACK_HOURS_KEY, DEFAULT_LOOKBACK_HOURS)
        return timezone.now() - timedelta(hours=lookback_hours)

    def _set_watermark(self, when):
        AppSetting.objects.update_or_create(key=WATERMARK_KEY, defaults={'value': when.isoformat()})

    def _get_projects(self):
        raw = get_app_setting(PROJECTS_KEY, DEFAULT_PROJECTS)
        return [key.strip() for key in raw.split(',') if key.strip()]

    def _get_int_setting(self, key, default):
        raw = get_app_setting(key, '')
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    def _notify_completion(self, range_mode, stats):
        usernames = [u.strip() for u in get_app_setting(NOTIFY_USERS_KEY, '').split(',') if u.strip()]
        team_id = get_app_setting(NOTIFY_TEAM_KEY, '')
        team = Team.objects.filter(pk=team_id).first() if team_id.isdigit() else None

        # Combine into one recipient set (deduped by pk) so a user who is both
        # individually configured and a member of the configured team gets a
        # single notification, not two.
        recipients = set(User.objects.filter(username__in=usernames)) if usernames else set()
        if team:
            recipients |= set(team.members.all())

        if not recipients:
            return

        if range_mode:
            message = f"jira_reconcile last: Created {stats['tickets_created']} Updated {stats['events_created']}"
        else:
            message = f"jira_reconcile by_time: Updated: {stats['events_created']}"

        notify(message, source='jira_reconcile', users=recipients)

    # -- explicit key range ------------------------------------------------

    def _parse_key(self, key):
        project, _, num = key.rpartition('-')
        if not project or not num.isdigit():
            raise ValueError(f'Invalid issue key: {key!r} (expected e.g. GITIN-1500)')
        return project, int(num)

    def _iter_key_range(self, project, start_num, end_num):
        for num in range(start_num, end_num + 1):
            yield f'{project}-{num}'

    def _fetch_highest_issue_number(self, session, base_url, project):
        response = self._get(
            session,
            f'{base_url}/rest/api/3/search/jql',
            params={'jql': f'project = "{project}" ORDER BY key DESC', 'maxResults': 1, 'fields': 'key'},
        )
        issues = response.json().get('issues', [])
        if not issues:
            return None
        _, num = self._parse_key(issues[0]['key'])
        return num

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

    def _fetch_issue_fields(self, session, base_url, issue_key):
        # 'status' is fetched too, but only ever used to seed a *new* local ticket
        # (see _reconcile_issue) — for tickets that already exist locally, status is
        # only ever moved forward via an explicit changelog item, never the snapshot.
        try:
            response = self._get(
                session,
                f'{base_url}/rest/api/3/issue/{issue_key}',
                params={'fields': 'summary,project,issuetype,assignee,labels,parent,status'},
            )
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise
        return response.json().get('fields', {})

    def _iter_comments(self, session, base_url, issue_key):
        start_at = 0
        while True:
            response = self._get(
                session,
                f'{base_url}/rest/api/3/issue/{issue_key}/comment',
                params={'startAt': start_at, 'maxResults': PAGE_SIZE},
            )
            data = response.json()
            comments = data.get('comments', [])
            for comment in comments:
                yield comment
            start_at += len(comments)
            if not comments or start_at >= data.get('total', 0):
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

    def _reconcile_issue(self, session, base_url, issue_key, stats, create_missing=False):
        try:
            ticket = JiraTicket.objects.get(issue_key=issue_key)
        except JiraTicket.DoesNotExist:
            if not create_missing:
                logger.info('jira_reconcile_unknown_ticket_skipped', extra={'issue_key': issue_key})
                return

            fields = self._fetch_issue_fields(session, base_url, issue_key)
            if fields is None:
                logger.info('jira_reconcile_issue_not_found', extra={'issue_key': issue_key})
                stats['issues_not_found'] += 1
                return

            body_defaults = _ticket_defaults_from_fields(fields)
            initial_status = (fields.get('status') or {}).get('name', '')
            ticket = JiraTicket.objects.create(
                issue_key=issue_key, status=initial_status[:100], **body_defaults
            )
            stats['tickets_created'] += 1
            body_refreshed = False
        else:
            fields = self._fetch_issue_fields(session, base_url, issue_key)
            if fields is None:
                logger.info('jira_reconcile_issue_not_found', extra={'issue_key': issue_key})
                stats['issues_not_found'] += 1
                return

            body_defaults = _ticket_defaults_from_fields(fields)
            body_refreshed = any(getattr(ticket, key) != value for key, value in body_defaults.items())
            if body_refreshed:
                JiraTicket.objects.filter(pk=ticket.pk).update(**body_defaults)

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

        comments_created = 0
        for comment in self._iter_comments(session, base_url, issue_key):
            comment_id = comment.get('id')
            if JiraEvent.objects.filter(ticket=ticket, payload__comment__id=comment_id).exists():
                continue

            comment_created_at = parse_datetime(comment.get('created', '')) or timezone.now()

            payload = {
                'webhookEvent': 'jira:issue_commented',
                'issue': {'key': issue_key},
                'comment': comment,
                'source': 'jira_reconcile',
            }
            summary = _build_summary('jira:issue_commented', payload)

            JiraEvent.objects.create(
                ticket=ticket,
                event_type='jira:issue_commented',
                summary=summary,
                payload=payload,
                received_at=comment_created_at,
            )
            stats['comments_created'] += 1
            comments_created += 1

        changed = created_count or comments_created or body_refreshed
        logger.info(
            'jira_reconcile_issue_done',
            extra={
                'issue_key': issue_key,
                'outcome': 'updated' if changed else 'unchanged',
                'status_events': created_count,
                'comments_created': comments_created,
                'body_refreshed': body_refreshed,
            },
        )
