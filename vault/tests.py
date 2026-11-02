from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Team
from settings_hub.models import AppSetting

from .crypto import encrypt_for_credential
from .models import Container, ContainerAccess, Credential
from .views import clipboard_ttl_seconds

SECRET = 'S3cr3t-Pa55word'
PASSPHRASE = 'Pa55phrase-xyz'
PRIVATE_KEY = '-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkq\n-----END PRIVATE KEY-----'


def make_credential(owner, credential_type=Credential.TYPE_PASSWORD, **fields):
    credential = Credential(owner=owner, credential_type=credential_type, name=fields.pop('name', 'Prod DB'), **fields)
    credential.save()
    return credential


def set_secret(credential, owner, field, plaintext):
    setattr(credential, field, encrypt_for_credential(credential, owner, plaintext))
    credential.save()


class CredentialDetailTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('ope_test', password='x')
        self.outsider = User.objects.create_user('agent_test', password='x')
        self.credential = make_credential(self.owner, url='https://db.example.com', username='admin')
        set_secret(self.credential, self.owner, 'encrypted_password', SECRET)
        self.url = reverse('vault-detail', args=[self.credential.pk])

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_owner_sees_metadata_and_copy_buttons(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Prod DB')
        self.assertContains(response, 'https://db.example.com')
        self.assertContains(response, 'admin')
        self.assertContains(response, 'data-copy-secret="key"')
        self.assertContains(response, 'data-copy-target="f-url"')
        self.assertContains(response, 'data-copy-target="f-username"')

    def test_page_never_contains_secret_or_ciphertext(self):
        self.client.force_login(self.owner)
        html = self.client.get(self.url).content.decode()
        self.assertNotIn(SECRET, html)
        self.assertNotIn(self.credential.encrypted_password, html)

    def test_no_access_is_403(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_soft_deleted_is_404(self):
        self.credential.is_deleted = True
        self.credential.save()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_missing_is_404(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('vault-detail', args=[99999])).status_code, 404)

    def test_legacy_team_member_can_open_but_not_edit(self):
        team = Team.objects.create(name='Ops')
        team.members.add(self.outsider)
        self.credential.visibility = Credential.VIS_TEAM
        self.credential.team = team
        self.credential.save()
        self.client.force_login(self.outsider)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse('vault-edit', args=[self.credential.pk]))

    def test_container_grant_read_and_read_write(self):
        team = Team.objects.create(name='Devs')
        team.members.add(self.outsider)
        parent = Container.objects.create(name='Infra', created_by=self.owner)
        container = Container.objects.create(name='Databases', parent=parent, created_by=self.owner)
        grant = ContainerAccess.objects.create(container=container, team=team, access_level='read')
        credential = make_credential(self.owner, container=container, name='Shared')
        url = reverse('vault-detail', args=[credential.pk])
        edit_url = reverse('vault-edit', args=[credential.pk])
        self.client.force_login(self.outsider)
        response = self.client.get(url)
        self.assertContains(response, 'Infra / Databases')
        self.assertNotContains(response, edit_url)
        grant.access_level = 'read_write'
        grant.save()
        self.assertContains(self.client.get(url), edit_url)

    def test_owner_sees_edit(self):
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(self.url), reverse('vault-edit', args=[self.credential.pk]))

    def test_secret_row_absent_when_field_empty(self):
        empty = make_credential(self.owner, name='Empty')
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(reverse('vault-detail', args=[empty.pk])), 'data-copy-secret="')

    def test_api_key_has_key_and_secret_buttons(self):
        credential = make_credential(self.owner, Credential.TYPE_API_KEY, name='API')
        set_secret(credential, self.owner, 'encrypted_password', SECRET)
        set_secret(credential, self.owner, 'encrypted_passphrase', PASSPHRASE)
        self.client.force_login(self.owner)
        html = self.client.get(reverse('vault-detail', args=[credential.pk])).content.decode()
        self.assertIn('data-copy-secret="key"', html)
        self.assertIn('data-copy-secret="secret"', html)
        self.assertNotIn(SECRET, html)
        self.assertNotIn(PASSPHRASE, html)

    def test_ssh_key_shows_public_key_but_never_the_private_key(self):
        credential = make_credential(self.owner, Credential.TYPE_SSH_KEY, name='SSH', public_key='ssh-ed25519 AAAAC3Nza user@host')
        set_secret(credential, self.owner, 'encrypted_private_key', PRIVATE_KEY)
        self.client.force_login(self.owner)
        html = self.client.get(reverse('vault-detail', args=[credential.pk])).content.decode()
        self.assertIn('ssh-ed25519 AAAAC3Nza user@host', html)
        self.assertIn('data-copy-secret="key"', html)
        self.assertNotIn('MIIEvQIBADANBgkq', html)
        self.assertNotIn(credential.encrypted_private_key, html)

    def test_certificate_shows_pem_but_never_the_private_key(self):
        credential = make_credential(self.owner, Credential.TYPE_CERTIFICATE, name='Cert', certificate_pem='-----BEGIN CERTIFICATE-----\nAAA\n-----END CERTIFICATE-----')
        set_secret(credential, self.owner, 'encrypted_private_key', PRIVATE_KEY)
        self.client.force_login(self.owner)
        html = self.client.get(reverse('vault-detail', args=[credential.pk])).content.decode()
        self.assertIn('BEGIN CERTIFICATE', html)
        self.assertNotIn('MIIEvQIBADANBgkq', html)

    def test_copy_response_is_no_store_and_returns_the_secret(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('vault-copy', args=[self.credential.pk]), {'field': 'key'})
        self.assertEqual(response.json(), {'secret': SECRET})
        self.assertIn('no-store', response['Cache-Control'])

    def test_ttl_reaches_the_page(self):
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(self.url), 'const clipboardTtl = 30;')
        AppSetting.objects.create(key='vault_clipboard_ttl_seconds', value='45')
        self.assertContains(self.client.get(self.url), 'const clipboardTtl = 45;')

    def test_ttl_zero_hides_the_notice(self):
        AppSetting.objects.create(key='vault_clipboard_ttl_seconds', value='0')
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertContains(response, 'const clipboardTtl = 0;')
        self.assertNotContains(response, 'is cleared from the clipboard')


class VaultListLinkTests(TestCase):
    def test_list_links_to_the_page_and_shares_the_ttl_script(self):
        owner = User.objects.create_user('ope_test', password='x')
        credential = make_credential(owner)
        self.client.force_login(owner)
        response = self.client.get(reverse('vault-list'))
        self.assertContains(response, reverse('vault-detail', args=[credential.pk]))
        self.assertContains(response, 'const clipboardTtl = 30;')
        self.assertContains(response, 'copyToClipboard(data.secret, true)')


class ClipboardTtlSettingTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('admin_t', password='x', is_staff=True)
        self.user = User.objects.create_user('agent_test', password='x')
        self.url = reverse('settings-vault-clipboard-ttl')

    def test_default_is_30(self):
        self.assertEqual(clipboard_ttl_seconds(), 30)

    def test_invalid_stored_value_falls_back_to_default(self):
        AppSetting.objects.create(key='vault_clipboard_ttl_seconds', value='abc')
        self.assertEqual(clipboard_ttl_seconds(), 30)

    def test_staff_saves_one_value_for_every_user(self):
        self.client.force_login(self.staff)
        self.client.post(self.url, {'ttl': '60'})
        self.assertEqual(clipboard_ttl_seconds(), 60)
        self.assertEqual(AppSetting.objects.filter(key='vault_clipboard_ttl_seconds').count(), 1)
        self.client.force_login(self.user)
        owner_cred = make_credential(self.user)
        self.assertContains(self.client.get(reverse('vault-detail', args=[owner_cred.pk])), 'const clipboardTtl = 60;')

    def test_zero_is_accepted(self):
        self.client.force_login(self.staff)
        self.client.post(self.url, {'ttl': '0'})
        self.assertEqual(clipboard_ttl_seconds(), 0)

    def test_invalid_values_are_rejected(self):
        self.client.force_login(self.staff)
        for bad in ('-1', '3601', 'abc', ''):
            self.client.post(self.url, {'ttl': bad})
        self.assertFalse(AppSetting.objects.filter(key='vault_clipboard_ttl_seconds').exists())

    def test_non_staff_cannot_change_it(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {'ttl': '5'})
        self.assertIn(response.status_code, (302, 403))
        self.assertFalse(AppSetting.objects.filter(key='vault_clipboard_ttl_seconds').exists())

    def test_settings_page_shows_the_current_value(self):
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse('settings-vault')), 'name="ttl" value="30"')
