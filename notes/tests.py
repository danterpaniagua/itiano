import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import UserProfile
from itsm.models import Ticket
from jira_integration.models import JiraTicket
from vault.crypto import encrypt_for_credential
from vault.models import Credential

from .mentions import find_mentions, parse_mentions, render_mentions, resolve, search, sync_mentions
from .models import Note, NoteMention, NoteShare

SECRET = 'S3cr3t-Pa55word'


def make_user(name, role='requester'):
    user = User.objects.create_user(name, password='x')
    UserProfile.objects.update_or_create(user=user, defaults={'role': role})
    return User.objects.get(pk=user.pk)  # drop the profile cached by the creation signal


def make_credential(owner, name='Prod DB', credential_type='password', **fields):
    credential = Credential(owner=owner, name=name, credential_type=credential_type, **fields)
    credential.save()
    credential.encrypted_password = encrypt_for_credential(credential, owner, SECRET)
    credential.save()
    return credential


class ParserTests(TestCase):
    def kinds(self, body):
        return parse_mentions(body)

    def test_the_three_kinds(self):
        self.assertEqual(
            self.kinds('See @GITIN-2315, @ticket:42 and @cred:17.'),
            [('jira', 'GITIN-2315'), ('ticket', '42'), ('cred', '17')],
        )

    def test_email_is_not_a_mention(self):
        self.assertEqual(self.kinds('write to user@host.com or dev@GITIN-1'), [])

    def test_inline_code_is_ignored(self):
        self.assertEqual(self.kinds('use `@GITIN-1` here'), [])

    def test_fenced_blocks_are_ignored(self):
        body = 'before @GITIN-1\n```json\n{"a": "@GITIN-2", "b": "@cred:3"}\n```\nafter @GITIN-3'
        self.assertEqual(self.kinds(body), [('jira', 'GITIN-1'), ('jira', 'GITIN-3')])

    def test_longer_fence_closes_only_with_a_matching_fence(self):
        body = '````\n```\n@GITIN-1\n```\n````\n@GITIN-2'
        self.assertEqual(self.kinds(body), [('jira', 'GITIN-2')])

    def test_tilde_fences_are_ignored(self):
        self.assertEqual(self.kinds('~~~\n@GITIN-1\n~~~\n@GITIN-2'), [('jira', 'GITIN-2')])

    def test_duplicates_count_once_in_order(self):
        self.assertEqual(self.kinds('@GITIN-2 @GITIN-1 @GITIN-2'), [('jira', 'GITIN-2'), ('jira', 'GITIN-1')])

    def test_boundaries(self):
        self.assertEqual(self.kinds('@GITIN-2315x @GITIN-2315-1 @gitin-2315 @GITIN @ticket: @cred:x'), [])
        self.assertEqual(self.kinds('(@GITIN-1) "@ticket:5".'), [('jira', 'GITIN-1'), ('ticket', '5')])

    def test_reference_is_normalised(self):
        self.assertEqual(self.kinds('@ticket:007'), [('ticket', '7')])

    def test_offsets_match_the_original_text(self):
        body = '`x` then @GITIN-1'
        start, end, _, _ = find_mentions(body)[0]
        self.assertEqual(body[start:end], '@GITIN-1')


class SyncTests(TestCase):
    def setUp(self):
        self.owner = make_user('ope_test')
        self.client.force_login(self.owner)

    def test_saving_a_note_keeps_mentions_in_step(self):
        self.client.post(reverse('note-new'), {'title': 'T', 'body': '@GITIN-1 and @cred:5'})
        note = Note.objects.get(title='T')
        self.assertEqual(set(note.mentions.values_list('kind', 'ref')), {('jira', 'GITIN-1'), ('cred', '5')})
        self.client.post(reverse('note-edit', args=[note.pk]), {'title': 'T', 'body': '@GITIN-2'})
        self.assertEqual(list(note.mentions.values_list('kind', 'ref')), [('jira', 'GITIN-2')])

    def test_deleting_a_note_deletes_its_mentions(self):
        note = Note.objects.create(title='T', body='@GITIN-1', owner=self.owner)
        sync_mentions(note)
        note.delete()
        self.assertEqual(NoteMention.objects.count(), 0)


class ResolveTests(TestCase):
    def setUp(self):
        self.owner = make_user('ope_test')
        self.other = make_user('agent_test')

    def test_jira_states(self):
        JiraTicket.objects.create(issue_key='GITIN-1', title='Deploy', status='Open')
        JiraTicket.objects.create(issue_key='GITIN-2', title='Gone', is_deleted=True)
        ok = resolve(self.other, 'jira', 'GITIN-1')
        self.assertEqual((ok['state'], ok['label']), ('ok', 'GITIN-1 · Deploy'))
        self.assertEqual(ok['url'], reverse('jira-ticket-detail', args=['GITIN-1']))
        self.assertEqual(resolve(self.other, 'jira', 'GITIN-2')['state'], 'deleted')
        self.assertNotIn('Gone', resolve(self.other, 'jira', 'GITIN-2')['label'])
        self.assertEqual(resolve(self.other, 'jira', 'GITIN-9')['state'], 'not_found')

    def test_ticket_states_per_viewer(self):
        ticket = Ticket.objects.create(title='VPN down', description='d', type='incident', requester=self.owner)
        self.assertEqual(resolve(self.owner, 'ticket', str(ticket.pk))['label'], f'#{ticket.pk} · VPN down')
        denied = resolve(self.other, 'ticket', str(ticket.pk))
        self.assertEqual((denied['state'], denied['label']), ('no_access', 'ticket (no access)'))
        self.assertEqual(resolve(self.owner, 'ticket', '99999')['state'], 'not_found')

    def test_agent_sees_any_ticket(self):
        ticket = Ticket.objects.create(title='VPN down', description='d', type='incident', requester=self.owner)
        agent = make_user('agent2', 'agent')
        self.assertEqual(resolve(agent, 'ticket', str(ticket.pk))['state'], 'ok')

    def test_credential_states_per_viewer(self):
        credential = make_credential(self.owner, credential_type='ssh_key')
        ok = resolve(self.owner, 'cred', str(credential.pk))
        self.assertEqual((ok['state'], ok['label'], ok['icon']), ('ok', 'Prod DB', 'bi-terminal'))
        self.assertEqual(ok['url'], reverse('vault-detail', args=[credential.pk]))
        denied = resolve(self.other, 'cred', str(credential.pk))
        self.assertEqual((denied['state'], denied['label']), ('no_access', 'credential (no access)'))
        self.assertNotIn('Prod DB', str(denied))
        credential.is_deleted = True
        credential.save()
        self.assertEqual(resolve(self.owner, 'cred', str(credential.pk))['state'], 'deleted')
        self.assertEqual(resolve(self.other, 'cred', str(credential.pk))['state'], 'no_access')
        self.assertEqual(resolve(self.owner, 'cred', '99999')['state'], 'not_found')

    def test_chips_never_contain_secrets(self):
        credential = make_credential(self.owner)
        out = render_mentions(self.owner, f'@cred:{credential.pk}')
        self.assertIn('Prod DB', out)
        self.assertNotIn(SECRET, out)
        self.assertNotIn(credential.encrypted_password, out)

    def test_render_replaces_only_mentions_outside_code(self):
        JiraTicket.objects.create(issue_key='GITIN-1', title='Deploy')
        out = render_mentions(self.owner, 'a @GITIN-1 b `@GITIN-1` c')
        self.assertEqual(out.count('badge'), 1)
        self.assertIn('`@GITIN-1`', out)

    def test_titles_are_escaped_for_html_and_markdown(self):
        JiraTicket.objects.create(issue_key='GITIN-1', title='<script>x</script> *bold* _it_')
        out = render_mentions(self.owner, '@GITIN-1')
        self.assertNotIn('<script>', out)
        self.assertNotIn('*bold*', out)
        self.assertIn('&lt;script&gt;', out)


class ResolveEndpointTests(TestCase):
    def setUp(self):
        self.owner = make_user('ope_test')
        self.url = reverse('notes-mention-resolve')

    def test_anonymous_is_redirected(self):
        self.assertEqual(self.client.post(self.url, '{}', content_type='application/json').status_code, 302)

    def test_returns_the_body_with_chips_for_the_viewer(self):
        JiraTicket.objects.create(issue_key='GITIN-1', title='Deploy')
        self.client.force_login(self.owner)
        response = self.client.post(self.url, json.dumps({'body': 'x @GITIN-1'}), content_type='application/json')
        self.assertIn('GITIN-1 · Deploy', response.json()['body'])

    def test_bad_payload_gives_an_empty_body(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, 'not json', content_type='application/json')
        self.assertEqual(response.json(), {'body': ''})


class SearchTests(TestCase):
    def setUp(self):
        self.owner = make_user('ope_test')
        self.other = make_user('agent_test')
        JiraTicket.objects.create(issue_key='GITIN-2315', title='SmartPedidos deploy')
        JiraTicket.objects.create(issue_key='GITIN-2318', title='Fix invoice')
        JiraTicket.objects.create(issue_key='GITIN-9', title='Hidden', is_deleted=True)
        self.ticket = Ticket.objects.create(title='Deploy VPN', description='d', type='incident', requester=self.owner)
        self.credential = make_credential(self.owner, name='Deploy DB')

    def tokens(self, user, q):
        return [r['token'] for r in search(user, q)]

    def test_key_prefix_offers_jira_tickets_only(self):
        self.assertEqual(self.tokens(self.owner, 'GITIN-23'), ['@GITIN-2315', '@GITIN-2318'])

    def test_deleted_jira_tickets_are_not_offered(self):
        self.assertNotIn('@GITIN-9', self.tokens(self.owner, 'GITIN-'))

    def test_free_text_mixes_the_three_kinds(self):
        self.assertEqual(
            self.tokens(self.owner, 'deploy'),
            ['@GITIN-2315', f'@ticket:{self.ticket.pk}', f'@cred:{self.credential.pk}'],
        )

    def test_prefixes_restrict_the_kind(self):
        self.assertEqual(self.tokens(self.owner, 'ticket:deploy'), [f'@ticket:{self.ticket.pk}'])
        self.assertEqual(self.tokens(self.owner, 'cred:deploy'), [f'@cred:{self.credential.pk}'])
        self.assertEqual(self.tokens(self.owner, f'ticket:{self.ticket.pk:02d}'), [f'@ticket:{self.ticket.pk}'])

    def test_only_what_the_user_can_see(self):
        self.assertEqual(self.tokens(self.other, 'deploy'), ['@GITIN-2315'])
        self.assertEqual(self.tokens(self.other, 'cred:deploy'), [])

    def test_free_text_needs_two_characters(self):
        self.assertEqual(self.tokens(self.owner, 'd'), [])

    def test_a_prefix_lists_right_away(self):
        self.assertEqual(self.tokens(self.owner, 'cred:'), [f'@cred:{self.credential.pk}'])
        self.assertEqual(self.tokens(self.owner, 'ticket:'), [f'@ticket:{self.ticket.pk}'])
        self.assertEqual(self.tokens(self.owner, 'cred:d'), [f'@cred:{self.credential.pk}'])
        self.assertEqual(self.tokens(self.other, 'cred:'), [])

    def test_credential_rows_carry_container_and_tags(self):
        from vault.models import Container, Tag
        parent = Container.objects.create(name='Infra', created_by=self.owner)
        container = Container.objects.create(name='Databases', parent=parent, created_by=self.owner)
        tagged = make_credential(self.owner, name='Tagged DB', container=container)
        tagged.tags.add(Tag.objects.create(name='prod'))
        rows = {r['token']: r for r in search(self.owner, 'cred:tagged')}
        row = rows[f'@cred:{tagged.pk}']
        self.assertEqual((row['sub'], row['tags']), ('Infra / Databases', ['prod']))
        self.assertEqual(search(self.owner, 'cred:')[-1]['sub'] in ('Personal', 'Infra / Databases'), True)

    def test_personal_credential_shows_personal(self):
        self.assertEqual(search(self.owner, 'cred:deploy')[0]['sub'], 'Personal')

    def test_a_tag_name_matches_credentials(self):
        from vault.models import Tag
        self.credential.tags.add(Tag.objects.create(name='staging'))
        self.assertEqual(self.tokens(self.owner, 'cred:staging'), [f'@cred:{self.credential.pk}'])
        self.assertEqual(self.tokens(self.other, 'cred:staging'), [])

    def test_a_credential_can_be_found_by_id(self):
        self.assertEqual(self.tokens(self.owner, f'cred:{self.credential.pk}'), [f'@cred:{self.credential.pk}'])

    def test_at_most_eight_per_kind(self):
        for i in range(12):
            JiraTicket.objects.create(issue_key=f'BULK-{i}', title='bulk item')
        self.assertEqual(len(self.tokens(self.owner, 'bulk')), 8)

    def test_endpoint_returns_no_secret_or_ciphertext(self):
        self.client.force_login(self.owner)
        text = self.client.get(reverse('notes-mention-search'), {'q': 'cred:deploy'}).content.decode()
        self.assertIn('Deploy DB', text)
        self.assertNotIn(SECRET, text)
        self.assertNotIn(self.credential.encrypted_password, text)

    def test_endpoint_requires_login(self):
        self.assertEqual(self.client.get(reverse('notes-mention-search'), {'q': 'deploy'}).status_code, 302)


class BacklinkTests(TestCase):
    def setUp(self):
        self.owner = make_user('ope_test')
        self.reader = make_user('reader')
        self.outsider = make_user('outsider')
        self.jira = JiraTicket.objects.create(issue_key='GITIN-1', title='Deploy')
        self.ticket = Ticket.objects.create(title='VPN', description='d', type='incident', requester=self.owner)
        self.credential = make_credential(self.owner)
        self.note = Note.objects.create(
            title='Checklist note', owner=self.owner,
            body=f'@GITIN-1 @ticket:{self.ticket.pk} @cred:{self.credential.pk}',
        )
        sync_mentions(self.note)
        NoteShare.objects.create(note=self.note, shared_with=self.reader)

    def pages(self):
        return [
            reverse('jira-ticket-detail', args=['GITIN-1']),
            reverse('ticket-detail', args=[self.ticket.pk]),
            reverse('vault-detail', args=[self.credential.pk]),
        ]

    def test_owner_sees_the_panel_on_the_three_pages(self):
        self.client.force_login(self.owner)
        for url in self.pages():
            self.assertContains(self.client.get(url), 'Notes mentioning this', msg_prefix=url)
            self.assertContains(self.client.get(url), 'Checklist note', msg_prefix=url)

    def test_a_reader_with_access_sees_the_shared_note(self):
        self.client.force_login(self.reader)
        self.assertContains(self.client.get(self.pages()[0]), 'Checklist note')

    def test_an_outsider_sees_no_panel_and_no_title(self):
        self.client.force_login(self.outsider)
        response = self.client.get(self.pages()[0])
        self.assertNotContains(response, 'Notes mentioning this')
        self.assertNotContains(response, 'Checklist note')

    def test_no_panel_when_nothing_mentions_the_object(self):
        other = JiraTicket.objects.create(issue_key='GITIN-2', title='Other')
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(reverse('jira-ticket-detail', args=[other.issue_key])), 'Notes mentioning this')

    def test_the_count_only_includes_readable_notes(self):
        private = Note.objects.create(title='Private one', owner=self.owner, body='@GITIN-1')
        sync_mentions(private)
        self.client.force_login(self.reader)
        response = self.client.get(self.pages()[0])
        self.assertContains(response, 'Checklist note')
        self.assertNotContains(response, 'Private one')
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(self.pages()[0]), 'Private one')


class EditorMarkupTests(TestCase):
    def test_editor_has_the_menu_and_the_endpoints(self):
        owner = make_user('ope_test')
        self.client.force_login(owner)
        response = self.client.get(reverse('note-new'))
        self.assertContains(response, 'id="mention-menu"')
        self.assertContains(response, reverse('notes-mention-search'))
        self.assertContains(response, reverse('notes-mention-resolve'))
