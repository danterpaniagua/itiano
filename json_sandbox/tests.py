import json

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from json_sandbox.views import MAX_NOTE_PAYLOAD_BYTES, NOTEBOOK_NAME, build_note_body
from notes.models import Note, Notebook


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


class SandboxSaveAsNoteTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff', password='pass', is_staff=True)
        self.client.force_login(self.staff)
        self.url = reverse('sandbox')
        self.payload = json.dumps({'issue': {'key': 'PROJ-1', 'status': 'Open'}})

    def save(self, **fields):
        data = {'payload': self.payload, 'mode': 'jsonpath', 'save_note': '1'}
        data.update(fields)
        return self.client.post(self.url, data)

    def test_saves_jsonpath_work_with_sections_in_order(self):
        response = self.save(expression='$.issue.key', note_title='Key lookup')
        note = Note.objects.get()
        self.assertRedirects(response, reverse('note-edit', args=[note.pk]), fetch_redirect_response=False)
        self.assertEqual((note.title, note.owner), ('Key lookup', self.staff))
        self.assertEqual(note.notebook.name, NOTEBOOK_NAME)
        body = note.body
        order = [body.index(x) for x in ('Mode: jsonpath', 'Payload:', 'JSONPath:', 'Result:')]
        self.assertEqual(order, sorted(order))
        self.assertIn('"PROJ-1"', body.split('Result:')[1])
        self.assertIn('$.issue.key', body.split('JSONPath:')[1].split('Result:')[0])

    def test_saves_filter_mode_with_the_match_result(self):
        condition = json.dumps({'path': '$.issue.status', 'op': 'eq', 'value': 'Open'})
        self.save(mode='filter', filter_expr=condition)
        body = Note.objects.get().body
        self.assertIn('Mode: filter', body)
        self.assertIn('Filter:', body)
        self.assertIn('Filter matched: yes', body)
        self.assertNotIn('JSONPath:', body)

    def test_success_message_is_shown_on_the_note(self):
        response = self.client.post(self.url, {
            'payload': self.payload, 'expression': '$.issue.key', 'save_note': '1', 'note_title': 'My query',
        }, follow=True)
        self.assertContains(response, 'Saved to note')

    def test_default_title(self):
        self.save(expression='$.issue.key')
        self.assertTrue(Note.objects.get().title.startswith('JSON sandbox - '))

    def test_notebook_is_created_once_and_reused(self):
        self.save(expression='$.issue.key')
        self.save(expression='$.issue.status')
        self.assertEqual(Notebook.objects.filter(owner=self.staff, name=NOTEBOOK_NAME).count(), 1)
        self.assertEqual(Note.objects.count(), 2)

    def test_empty_form_is_rejected(self):
        response = self.client.post(self.url, {'payload': '', 'mode': 'jsonpath', 'save_note': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Nothing to save')
        self.assertEqual(Note.objects.count(), 0)

    def test_oversized_payload_is_rejected(self):
        response = self.save(payload='x' * (MAX_NOTE_PAYLOAD_BYTES + 1), expression='$.a')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'too large')
        self.assertEqual(Note.objects.count(), 0)

    def test_non_staff_cannot_save(self):
        regular = User.objects.create_user('user', password='pass')
        self.client.force_login(regular)
        self.assertEqual(self.save(expression='$.a').status_code, 403)
        self.assertEqual(Note.objects.count(), 0)

    def test_invalid_payload_is_saved_as_typed_without_a_result(self):
        self.save(payload='{not json', expression='$.a')
        body = Note.objects.get().body
        self.assertIn('{not json', body)
        self.assertNotIn('Result:', body)

    def test_expression_not_evaluated_has_no_result_section(self):
        self.save(expression='')
        body = Note.objects.get().body
        self.assertNotIn('JSONPath:', body)
        self.assertNotIn('Result', body)

    def test_no_match_is_recorded(self):
        self.save(expression='$.nonexistent')
        self.assertIn('Result: no matches', Note.objects.get().body)

    def test_enter_in_the_form_never_saves(self):
        # Without save_note the POST only evaluates.
        self.client.post(self.url, {'payload': self.payload, 'expression': '$.issue.key', 'mode': 'jsonpath'})
        self.assertEqual(Note.objects.count(), 0)

    def test_button_is_not_a_submit_and_is_mobile_friendly(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Save as note')
        self.assertContains(response, 'onclick="saveAsNote()"')
        self.assertContains(response, 'flex-wrap')


class BuildNoteBodyTests(TestCase):
    def test_fence_grows_when_the_content_has_backticks(self):
        body = build_note_body('jsonpath', '{"a": "```"}', '$.a', '', None, None)
        self.assertIn('````json', body)

    def test_empty_sections_are_skipped(self):
        body = build_note_body('filter', '', '', '', None, None)
        self.assertEqual(body, 'Mode: filter\n')
