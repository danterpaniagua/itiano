from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Team

from .models import Notification, notify


class NotifyHelperTests(TestCase):
    def test_requires_exactly_one_of_users_or_team(self):
        with self.assertRaises(ValueError):
            notify('hi')
        with self.assertRaises(ValueError):
            notify('hi', users=[], team=Team.objects.create(name='T'))

    def test_single_user(self):
        user = User.objects.create(username='alice')
        created = notify('hello', users=user, source='test')
        self.assertEqual(len(created), 1)
        self.assertEqual(Notification.objects.get().user, user)

    def test_empty_users_is_noop(self):
        created = notify('hello', users=[])
        self.assertEqual(created, [])
        self.assertEqual(Notification.objects.count(), 0)

    def test_team_fans_out_to_current_members(self):
        u1 = User.objects.create(username='u1')
        u2 = User.objects.create(username='u2')
        team = Team.objects.create(name='Team A')
        team.members.set([u1, u2])

        created = notify('shared with team', team=team, source='vault_share')

        self.assertEqual(len(created), 2)
        self.assertEqual(set(Notification.objects.values_list('user__username', flat=True)), {'u1', 'u2'})

    def test_message_truncated_to_field_max_length(self):
        notify('x' * 600, users=User.objects.create(username='bob'))
        self.assertEqual(len(Notification.objects.get().message), 500)


class NotificationViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='viewer')
        self.other = User.objects.create(username='other')
        self.client = Client()
        self.client.force_login(self.user)

    def test_list_requires_login(self):
        anon = Client()
        response = anon.get(reverse('notifications-list'))
        self.assertEqual(response.status_code, 302)

    def test_list_shows_only_own_notifications(self):
        notify('mine', users=self.user)
        notify('not mine', users=self.other)
        response = self.client.get(reverse('notifications-list'))
        self.assertContains(response, 'mine')
        self.assertNotContains(response, 'not mine')

    def test_open_marks_read_and_redirects_to_url(self):
        notification = Notification.objects.create(user=self.user, message='m', url='/vault/')
        response = self.client.get(reverse('notifications-open', args=[notification.pk]))
        self.assertRedirects(response, '/vault/', fetch_redirect_response=False)
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)

    def test_open_falls_back_to_list_when_no_url(self):
        notification = Notification.objects.create(user=self.user, message='m', url='')
        response = self.client.get(reverse('notifications-open', args=[notification.pk]))
        self.assertRedirects(response, reverse('notifications-list'))

    def test_cannot_open_another_users_notification(self):
        notification = Notification.objects.create(user=self.other, message='m')
        response = self.client.get(reverse('notifications-open', args=[notification.pk]))
        self.assertEqual(response.status_code, 404)

    def test_mark_all_read_only_affects_current_user(self):
        notify('mine', users=self.user)
        notify('not mine', users=self.other)
        self.client.post(reverse('notifications-mark-all-read'), {'next': reverse('notifications-list')})
        self.assertEqual(Notification.objects.filter(user=self.user, read_at__isnull=True).count(), 0)
        self.assertEqual(Notification.objects.filter(user=self.other, read_at__isnull=True).count(), 1)

    def test_mark_all_read_rejects_offsite_next(self):
        response = self.client.post(reverse('notifications-mark-all-read'), {'next': 'https://evil.example/'})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('evil.example', response.headers['Location'])
