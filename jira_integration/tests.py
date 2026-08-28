import hashlib
import hmac
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from settings_hub.models import AppSetting

from .management.commands.jira_reconcile import WATERMARK_KEY
from .models import JiraEvent, JiraTicket
from .views import _build_summary

SAMPLE_PAYLOAD = {
    'webhookEvent': 'jira:issue_updated',
    'issue': {
        'key': 'PROJ-1',
        'fields': {
            'summary': 'Fix login bug',
            'project': {'key': 'PROJ'},
            'issuetype': {'name': 'Bug'},
            'status': {'name': 'In Progress'},
        },
    },
    'changelog': {
        'items': [
            {'field': 'status', 'fromString': 'Open', 'toString': 'In Progress'},
        ]
    },
}


def _make_signature(secret, body):
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f'sha256={sig}'


TEST_SECRET = 'testsecret'


class WebhookViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse('jira-webhook')
        self.body = json.dumps(SAMPLE_PAYLOAD).encode()

    def _signed_post(self, body):
        sig = _make_signature(TEST_SECRET, body)
        with self.settings(JIRA_WEBHOOK_SECRET=TEST_SECRET):
            return self.client.post(
                self.url,
                data=body,
                content_type='application/json',
                HTTP_X_HUB_SIGNATURE=sig,
            )

    def test_rejects_get(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_valid_payload_no_secret(self):
        with self.settings(JIRA_WEBHOOK_SECRET=''):
            response = self.client.post(
                self.url, data=self.body, content_type='application/json'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(JiraTicket.objects.count(), 1)
        self.assertEqual(JiraEvent.objects.count(), 1)

    def test_invalid_signature_rejected(self):
        with self.settings(JIRA_WEBHOOK_SECRET=TEST_SECRET):
            response = self.client.post(
                self.url,
                data=self.body,
                content_type='application/json',
                HTTP_X_HUB_SIGNATURE='sha256=invalidsig',
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(JiraTicket.objects.count(), 0)

    def test_valid_signature_accepted(self):
        response = self._signed_post(self.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(JiraTicket.objects.count(), 1)

    def test_second_event_reuses_ticket(self):
        self._signed_post(self.body)
        self._signed_post(self.body)
        self.assertEqual(JiraTicket.objects.count(), 1)
        self.assertEqual(JiraEvent.objects.count(), 2)

    def test_payload_without_issue_returns_200(self):
        body = json.dumps({'webhookEvent': 'jira:issue_updated'}).encode()
        response = self._signed_post(body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(JiraTicket.objects.count(), 0)

    def test_invalid_json_returns_400(self):
        response = self._signed_post(b'not json')
        self.assertEqual(response.status_code, 400)

    def test_received_at_uses_payload_timestamp_when_present(self):
        payload = dict(SAMPLE_PAYLOAD, timestamp=1798758000000)  # 2026-12-31T23:00:00Z
        body = json.dumps(payload).encode()
        self._signed_post(body)
        event = JiraEvent.objects.get()
        self.assertEqual(event.received_at, parse_datetime('2026-12-31T23:00:00+00:00'))


class BuildSummaryTests(TestCase):
    def test_changelog_items(self):
        summary = _build_summary('jira:issue_updated', SAMPLE_PAYLOAD)
        self.assertIn('status', summary)
        self.assertIn('In Progress', summary)

    def test_comment_fallback(self):
        payload = {
            'webhookEvent': 'jira:issue_commented',
            'issue': {},
            'comment': {'author': {'displayName': 'Alice'}},
        }
        summary = _build_summary('jira:issue_commented', payload)
        self.assertIn('Alice', summary)

    def test_event_type_fallback(self):
        payload = {'webhookEvent': 'jira:issue_created', 'issue': {}}
        summary = _build_summary('jira:issue_created', payload)
        self.assertIsInstance(summary, str)
        self.assertTrue(len(summary) > 0)


class TicketListViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('agent', password='pass')
        self.url = reverse('jira-ticket-list')

    def test_redirects_anonymous(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_returns_200_for_authenticated(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_lists_tickets(self):
        JiraTicket.objects.create(issue_key='PROJ-1', title='Bug', status='Open')
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertContains(response, 'PROJ-1')


class TicketDetailViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('agent', password='pass')
        self.ticket = JiraTicket.objects.create(issue_key='PROJ-1', title='Bug', status='Open')
        self.url = reverse('jira-ticket-detail', args=['PROJ-1'])

    def test_returns_200(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PROJ-1')

    def test_unknown_key_returns_404(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('jira-ticket-detail', args=['UNKNOWN-99']))
        self.assertEqual(response.status_code, 404)


class OpenInSandboxViewTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff', password='pass', is_staff=True)
        self.regular = User.objects.create_user('user', password='pass', is_staff=False)
        self.ticket = JiraTicket.objects.create(issue_key='PROJ-1', title='Bug', status='Open')
        self.event = JiraEvent.objects.create(
            ticket=self.ticket,
            event_type='jira:issue_updated',
            summary='status changed',
            payload=SAMPLE_PAYLOAD,
        )
        self.url = reverse('jira-open-sandbox', args=['PROJ-1', self.event.pk])

    def test_non_staff_gets_403(self):
        self.client.force_login(self.regular)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_staff_sets_session_and_redirects(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('sandbox_payload', self.client.session)


class FakeResponse:
    def __init__(self, json_data, status_code=200, headers=None):
        self._json_data = json_data
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f'HTTP {self.status_code}')


def _changelog_history(history_id, to_status, created):
    return {
        'id': history_id,
        'created': created,
        'items': [{'field': 'status', 'fromString': 'Open', 'toString': to_status}],
    }


def _mock_get(search_response, changelog_response, captured_jql=None,
               issue_response=None, comments_response=None):
    issue_response = issue_response if issue_response is not None else {'fields': {'summary': 'Bug'}}
    comments_response = comments_response if comments_response is not None else {'comments': [], 'total': 0}

    def _get(self, url, params=None, timeout=None):
        if url.endswith('/rest/api/3/search/jql'):
            if captured_jql is not None:
                captured_jql.append(params.get('jql', ''))
            return FakeResponse(search_response)
        if url.endswith('/changelog'):
            return FakeResponse(changelog_response)
        if url.endswith('/comment'):
            return FakeResponse(comments_response)
        return FakeResponse(issue_response)
    return _get


JIRA_SETTINGS = {
    'JIRA_API_BASE_URL': 'https://fake.atlassian.net',
    'JIRA_API_EMAIL': 'bot@example.com',
    'JIRA_API_TOKEN': 'faketoken',
}


class JiraReconcileCommandTests(TestCase):
    def _run(self):
        call_command('jira_reconcile')

    def test_missing_credentials_aborts(self):
        with self.settings(JIRA_API_BASE_URL='', JIRA_API_EMAIL='', JIRA_API_TOKEN=''):
            self._run()
        self.assertEqual(JiraEvent.objects.count(), 0)
        self.assertFalse(AppSetting.objects.filter(key=WATERMARK_KEY).exists())

    def test_backfills_missing_status_event_and_advances_watermark(self):
        JiraTicket.objects.create(issue_key='PROJ-1', title='Bug', status='Open')
        search_response = {'issues': [{'key': 'PROJ-1'}], 'total': 1}
        changelog_response = {
            'values': [_changelog_history('9001', 'In Progress', '2026-08-27T10:00:00.000+0000')],
            'total': 1,
        }
        with self.settings(**JIRA_SETTINGS), \
                patch('requests.Session.get', _mock_get(search_response, changelog_response)):
            self._run()

        self.assertEqual(JiraEvent.objects.count(), 1)
        event = JiraEvent.objects.get()
        self.assertEqual(event.payload['changelog']['id'], '9001')
        self.assertEqual(parse_datetime('2026-08-27T10:00:00.000+0000'), event.received_at)

        ticket = JiraTicket.objects.get(issue_key='PROJ-1')
        self.assertEqual(ticket.status, 'In Progress')
        self.assertTrue(AppSetting.objects.filter(key=WATERMARK_KEY).exists())

    def test_rerun_does_not_duplicate_events(self):
        JiraTicket.objects.create(issue_key='PROJ-1', title='Bug', status='Open')
        search_response = {'issues': [{'key': 'PROJ-1'}], 'total': 1}
        changelog_response = {
            'values': [_changelog_history('9001', 'In Progress', '2026-08-27T10:00:00.000+0000')],
            'total': 1,
        }
        with self.settings(**JIRA_SETTINGS), \
                patch('requests.Session.get', _mock_get(search_response, changelog_response)):
            self._run()
            self._run()

        self.assertEqual(JiraEvent.objects.count(), 1)

    def test_unknown_ticket_skipped_without_error(self):
        search_response = {'issues': [{'key': 'PROJ-404'}], 'total': 1}
        changelog_response = {'values': [], 'total': 0}
        with self.settings(**JIRA_SETTINGS), \
                patch('requests.Session.get', _mock_get(search_response, changelog_response)):
            self._run()

        self.assertEqual(JiraEvent.objects.count(), 0)
        self.assertEqual(JiraTicket.objects.count(), 0)

    def test_does_not_roll_back_newer_status(self):
        ticket = JiraTicket.objects.create(issue_key='PROJ-1', title='Bug', status='Done')
        JiraEvent.objects.create(
            ticket=ticket,
            event_type='jira:issue_updated',
            summary='status changed',
            payload={'changelog': {'id': 'live-1', 'items': [{'field': 'status', 'toString': 'Done'}]}},
            received_at=timezone.now(),
        )
        search_response = {'issues': [{'key': 'PROJ-1'}], 'total': 1}
        changelog_response = {
            'values': [_changelog_history('9001', 'In Progress', '2020-01-01T10:00:00.000+0000')],
            'total': 1,
        }
        with self.settings(**JIRA_SETTINGS), \
                patch('requests.Session.get', _mock_get(search_response, changelog_response)):
            self._run()

        # The older backfilled history is still recorded for the timeline...
        self.assertEqual(JiraEvent.objects.filter(payload__changelog__id='9001').count(), 1)
        # ...but it must not roll back the status the live webhook already set.
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'Done')

    def test_defaults_to_gitin_project_scope_when_unconfigured(self):
        search_response = {'issues': [], 'total': 0}
        captured = []
        with self.settings(**JIRA_SETTINGS), \
                patch('requests.Session.get', _mock_get(search_response, {}, captured)):
            self._run()

        self.assertEqual(len(captured), 1)
        self.assertIn('project in ("GITIN")', captured[0])

    def test_uses_configured_project_scope(self):
        AppSetting.objects.create(key='jira_reconcile_projects', value='PROJ, OPS')
        search_response = {'issues': [], 'total': 0}
        captured = []
        with self.settings(**JIRA_SETTINGS), \
                patch('requests.Session.get', _mock_get(search_response, {}, captured)):
            self._run()

        self.assertIn('project in ("PROJ", "OPS")', captured[0])

    def test_empty_project_scope_setting_scans_all_projects(self):
        AppSetting.objects.create(key='jira_reconcile_projects', value='')
        search_response = {'issues': [], 'total': 0}
        captured = []
        with self.settings(**JIRA_SETTINGS), \
                patch('requests.Session.get', _mock_get(search_response, {}, captured)):
            self._run()

        self.assertNotIn('project in', captured[0])

    def test_refreshes_body_fields_without_touching_status(self):
        ticket = JiraTicket.objects.create(issue_key='PROJ-1', title='Old title', status='Open')
        search_response = {'issues': [{'key': 'PROJ-1'}], 'total': 1}
        changelog_response = {'values': [], 'total': 0}
        issue_response = {
            'fields': {
                'summary': 'New title',
                'project': {'key': 'PROJ'},
                'issuetype': {'name': 'Bug'},
                'assignee': {'displayName': 'Alice', 'accountId': 'acc-1'},
                'labels': ['urgent'],
            }
        }
        with self.settings(**JIRA_SETTINGS), \
                patch('requests.Session.get', _mock_get(
                    search_response, changelog_response, issue_response=issue_response,
                )):
            self._run()

        ticket.refresh_from_db()
        self.assertEqual(ticket.title, 'New title')
        self.assertEqual(ticket.assignee, 'Alice')
        self.assertEqual(ticket.labels, ['urgent'])
        self.assertEqual(ticket.status, 'Open')

    def test_backfills_comments_and_dedupes_on_rerun(self):
        JiraTicket.objects.create(issue_key='PROJ-1', title='Bug', status='Open')
        search_response = {'issues': [{'key': 'PROJ-1'}], 'total': 1}
        changelog_response = {'values': [], 'total': 0}
        comments_response = {
            'comments': [{
                'id': 'c1',
                'created': '2026-08-27T10:00:00.000+0000',
                'author': {'displayName': 'Bob'},
                'body': {'type': 'doc'},
            }],
            'total': 1,
        }
        with self.settings(**JIRA_SETTINGS), \
                patch('requests.Session.get', _mock_get(
                    search_response, changelog_response, comments_response=comments_response,
                )):
            self._run()
            self._run()

        events = JiraEvent.objects.filter(event_type='jira:issue_commented')
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.get().payload['comment']['id'], 'c1')
