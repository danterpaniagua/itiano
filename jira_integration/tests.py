import hashlib
import hmac
import json

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

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
