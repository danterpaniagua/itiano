import json

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse


class SandboxAccessTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff', password='pass', is_staff=True)
        self.regular = User.objects.create_user('user', password='pass', is_staff=False)
        self.url = reverse('sandbox')

    def test_redirects_anonymous(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_non_staff_gets_403(self):
        self.client.force_login(self.regular)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_staff_gets_200(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


class SandboxEvaluationTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff', password='pass', is_staff=True)
        self.client.force_login(self.staff)
        self.url = reverse('sandbox')
        self.payload = json.dumps({'issue': {'key': 'PROJ-1', 'status': 'Open'}})

    def test_valid_jsonpath_returns_result(self):
        response = self.client.post(self.url, {
            'payload': self.payload,
            'expression': '$.issue.key',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PROJ-1')

    def test_invalid_jsonpath_returns_error(self):
        response = self.client.post(self.url, {
            'payload': self.payload,
            'expression': '!!!invalid',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'JSONPath error')

    def test_no_match_shows_warning(self):
        response = self.client.post(self.url, {
            'payload': self.payload,
            'expression': '$.nonexistent',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No matches found')

    def test_invalid_json_returns_error(self):
        response = self.client.post(self.url, {
            'payload': 'not valid json',
            'expression': '$.key',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid JSON')


class SandboxSessionPreloadTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff', password='pass', is_staff=True)
        self.client.force_login(self.staff)
        self.url = reverse('sandbox')

    def test_session_payload_preloaded(self):
        session = self.client.session
        session['sandbox_payload'] = '{"key": "value"}'
        session.save()
        response = self.client.get(self.url)
        self.assertContains(response, '{"key": "value"}')

    def test_session_payload_cleared_after_get(self):
        session = self.client.session
        session['sandbox_payload'] = '{"key": "value"}'
        session.save()
        self.client.get(self.url)
        self.assertNotIn('sandbox_payload', self.client.session)


class SandboxBackButtonTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff', password='pass', is_staff=True)
        self.client.force_login(self.staff)
        self.url = reverse('sandbox')

    def test_show_back_false_on_direct_access(self):
        response = self.client.get(self.url)
        self.assertFalse(response.context['show_back'])

    def test_show_back_true_with_get_param(self):
        response = self.client.get(self.url + '?back=1')
        self.assertTrue(response.context['show_back'])

    def test_show_back_persists_through_post(self):
        response = self.client.post(self.url, {
            'payload': '{}',
            'expression': '$.key',
            'back': '1',
        })
        self.assertTrue(response.context['show_back'])
