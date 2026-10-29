from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Team
from settings_hub.models import AppSetting

from .models import ENABLED_KEY, Notification, notify


class NotifyHelperTests(TestCase):
    def test_requires_exactly_one_of_users_or_team(self):
        with self.assertRaises(ValueError):
            notify('hi')
        with self.assertRaises(ValueError):
            notify('hi', users=[], team=Team.objects.create(name='T'))

    def test_validates_arguments_even_when_disabled(self):
        AppSetting.objects.create(key=ENABLED_KEY, value='False')
        with self.assertRaises(ValueError):
            notify('hi')

    def test_disabled_system_wide_is_a_noop(self):
        AppSetting.objects.create(key=ENABLED_KEY, value='False')
        user = User.objects.create(username='ghost')
        created = notify('hello', users=user)
        self.assertEqual(created, [])
        self.assertEqual(Notification.objects.count(), 0)

    def test_enabled_by_default_when_unset(self):
        user = User.objects.create(username='present')
        created = notify('hello', users=user)
        self.assertEqual(len(created), 1)

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


from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.utils import timezone

from core.models import UserProfile
from jira_integration.models import JiraTicket

from . import rules
from .models import NotificationRule, NotificationRuleHit


def _make_ticket(key, labels=None, project='GITIN', age_minutes=60, account_id='', **kwargs):
    ticket = JiraTicket.objects.create(
        issue_key=key, title=f'Title {key}', project_key=project, labels=labels or [],
        assignee_account_id=account_id, **kwargs,
    )
    JiraTicket.objects.filter(pk=ticket.pk).update(created_at=timezone.now() - timedelta(minutes=age_minutes))
    ticket.refresh_from_db()
    return ticket


def _make_rule(user=None, **kwargs):
    rule = NotificationRule.objects.create(
        name=kwargs.pop('name', 'Untagged GITIN'),
        filter=kwargs.pop('filter', rules.DEFAULT_FILTER),
        message=kwargs.pop('message', rules.DEFAULT_MESSAGE),
        grace_minutes=kwargs.pop('grace_minutes', 15),
        **kwargs,
    )
    # starts_at is auto_now_add; push it back so pre-existing test tickets qualify
    NotificationRule.objects.filter(pk=rule.pk).update(starts_at=timezone.now() - timedelta(days=1))
    rule.refresh_from_db()
    if user:
        rule.users.add(user)
    return rule


class ValidateFilterTests(TestCase):
    def test_default_filter_is_valid(self):
        self.assertIsNone(rules.validate_filter(rules.DEFAULT_FILTER))

    def test_rejects_empty_and_non_dict(self):
        self.assertIsNotNone(rules.validate_filter({}))
        self.assertIsNotNone(rules.validate_filter(['x']))

    def test_rejects_unknown_op(self):
        self.assertIn('Unsupported op', rules.validate_filter({'path': '$.a', 'op': 'nope', 'value': 1}))

    def test_rejects_malformed_nodes(self):
        self.assertIsNotNone(rules.validate_filter({'and': []}))
        self.assertIsNotNone(rules.validate_filter({'and': [{'op': 'eq', 'value': 1}]}))
        self.assertIsNotNone(rules.validate_filter({'path': 'issue.key', 'op': 'eq', 'value': 1}))
        self.assertIsNotNone(rules.validate_filter({'path': '$.a', 'op': 'in', 'value': 'x'}))
        self.assertIsNotNone(rules.validate_filter({'path': '$.a', 'op': 'eq'}))
        self.assertIsNotNone(rules.validate_filter({'path': '$.a', 'op': 'regex', 'value': '('}))

    def test_exists_needs_no_value(self):
        self.assertIsNone(rules.validate_filter({'path': '$.a', 'op': 'exists'}))

    def test_message_placeholders(self):
        self.assertIsNone(rules.validate_message('Ticket {key}: {title}'))
        self.assertIsNotNone(rules.validate_message('Ticket {bogus}'))
        self.assertIsNotNone(rules.validate_message('Ticket {key'))


class PayloadAndMatchTests(TestCase):
    def test_payload_is_jira_shaped(self):
        ticket = _make_ticket('GITIN-1', labels=['A'], account_id='acc1')
        payload = rules.build_payload(ticket)
        self.assertEqual(payload['issue']['key'], 'GITIN-1')
        self.assertEqual(payload['issue']['fields']['project']['key'], 'GITIN')
        self.assertEqual(payload['issue']['fields']['labels'], ['A'])
        self.assertEqual(payload['issue']['fields']['assignee']['accountId'], 'acc1')

    def test_no_labels_matches_not_in_ci(self):
        self.assertTrue(rules.ticket_matches(rules.DEFAULT_FILTER, _make_ticket('GITIN-1', labels=[])))

    def test_other_labels_match(self):
        self.assertTrue(rules.ticket_matches(rules.DEFAULT_FILTER, _make_ticket('GITIN-1', labels=['SRE'])))

    def test_tag_present_case_insensitive_does_not_match(self):
        self.assertFalse(rules.ticket_matches(rules.DEFAULT_FILTER, _make_ticket('GITIN-1', labels=['infradevops'])))

    def test_other_project_does_not_match(self):
        self.assertFalse(rules.ticket_matches(rules.DEFAULT_FILTER, _make_ticket('OPS-1', project='OPS')))

    def test_several_projects_with_in(self):
        flt = {'path': '$.issue.fields.project.key', 'op': 'in', 'value': ['GITIN', 'OPS']}
        self.assertTrue(rules.ticket_matches(flt, _make_ticket('OPS-1', project='OPS')))


class RunRuleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='ops')

    def test_notifies_once_across_runs(self):
        _make_ticket('GITIN-1')
        rule = _make_rule(self.user)
        self.assertEqual(rules.run_rule(rule), 1)
        self.assertEqual(rules.run_rule(rule), 0)
        self.assertEqual(Notification.objects.filter(user=self.user, source='jira_rule').count(), 1)
        self.assertEqual(NotificationRuleHit.objects.filter(rule=rule).count(), 1)

    def test_message_and_url(self):
        _make_ticket('GITIN-1')
        rules.run_rule(_make_rule(self.user))
        note = Notification.objects.get()
        self.assertEqual(note.message, 'Untagged ticket GITIN-1: Title GITIN-1')
        self.assertEqual(note.url, '/time/report/ticket/GITIN-1/timeline/')

    def test_jira_base_url_link(self):
        AppSetting.objects.create(key='jira_base_url', value='https://x.atlassian.net/')
        _make_ticket('GITIN-1')
        rules.run_rule(_make_rule(self.user))
        self.assertEqual(Notification.objects.get().url, 'https://x.atlassian.net/browse/GITIN-1')

    def test_grace_period_skips_recent_tickets(self):
        _make_ticket('GITIN-1', age_minutes=5)
        self.assertEqual(rules.run_rule(_make_rule(self.user, grace_minutes=15)), 0)

    def test_tagged_within_grace_never_alerts(self):
        ticket = _make_ticket('GITIN-1', age_minutes=5)
        rule = _make_rule(self.user, grace_minutes=15)
        rules.run_rule(rule)
        JiraTicket.objects.filter(pk=ticket.pk).update(labels=['INFRADEVOPS'])
        later = timezone.now() + timedelta(minutes=30)
        self.assertEqual(rules.run_rule(rule, later), 0)

    def test_starts_at_cutoff_no_retroactive_alerts(self):
        _make_ticket('GITIN-OLD', age_minutes=600)
        rule = NotificationRule.objects.create(
            name='New', filter=rules.DEFAULT_FILTER, message='{key}', grace_minutes=0,
        )
        rule.users.add(self.user)
        self.assertEqual(rules.run_rule(rule), 0)

    def test_deleted_tickets_are_skipped(self):
        _make_ticket('GITIN-1', is_deleted=True)
        self.assertEqual(rules.run_rule(_make_rule(self.user)), 0)

    def test_two_rules_notify_independently(self):
        _make_ticket('GITIN-1')
        other = User.objects.create(username='dev')
        r1 = _make_rule(self.user, name='A')
        r2 = _make_rule(other, name='B')
        self.assertEqual(rules.run_rule(r1), 1)
        self.assertEqual(rules.run_rule(r2), 1)
        self.assertEqual(Notification.objects.count(), 2)

    def test_team_and_assignee_recipients_deduped(self):
        assignee = User.objects.create(username='assignee')
        UserProfile.objects.update_or_create(user=assignee, defaults={'jira_account_id': 'acc9'})
        team = Team.objects.create(name='Ops')
        team.members.set([assignee, self.user])
        _make_ticket('GITIN-1', account_id='acc9')
        rule = _make_rule(self.user, notify_assignee=True)
        rule.teams.add(team)
        rules.run_rule(rule)
        self.assertEqual(Notification.objects.filter(user=assignee).count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)

    def test_no_recipients_sends_nothing_and_records_no_hit(self):
        _make_ticket('GITIN-1')
        rule = _make_rule(notify_assignee=True)
        self.assertEqual(rules.run_rule(rule), 0)
        self.assertEqual(NotificationRuleHit.objects.count(), 0)

    def test_cap_per_run(self):
        for i in range(rules.MAX_NOTIFICATIONS_PER_RUN + 5):
            _make_ticket(f'GITIN-{i}')
        rule = _make_rule(self.user)
        self.assertEqual(rules.run_rule(rule), rules.MAX_NOTIFICATIONS_PER_RUN)
        self.assertEqual(rules.run_rule(rule), 5)


class RulesCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='ops')
        _make_ticket('GITIN-1')

    def _run(self):
        out = StringIO()
        call_command('jira_rules_check', stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_notifies_and_is_idempotent(self):
        _make_rule(self.user)
        self._run()
        self._run()
        self.assertEqual(Notification.objects.count(), 1)

    def test_disabled_system_wide_records_nothing(self):
        AppSetting.objects.create(key=ENABLED_KEY, value='False')
        _make_rule(self.user)
        self._run()
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(NotificationRuleHit.objects.count(), 0)

    def test_inactive_rule_is_skipped(self):
        _make_rule(self.user, is_active=False)
        self._run()
        self.assertEqual(Notification.objects.count(), 0)

    def test_failing_rule_does_not_stop_others(self):
        broken = _make_rule(self.user, name='A broken', filter={'path': '$.x', 'op': 'regex', 'value': '('})
        _make_rule(self.user, name='B good')
        self._run()
        self.assertTrue(NotificationRule.objects.filter(pk=broken.pk).exists())
        self.assertEqual(Notification.objects.count(), 1)


class RuleSettingsViewTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('boss', password='x', is_staff=True)
        self.plain = User.objects.create_user('plain', password='x')
        self.client = Client()

    def _post_data(self, **overrides):
        import json
        data = {
            'name': 'R', 'is_active': 'on', 'filter': json.dumps(rules.DEFAULT_FILTER),
            'grace_minutes': '15', 'message': 'Untagged {key}',
        }
        data.update(overrides)
        return data

    def test_staff_only(self):
        self.client.login(username='plain', password='x')
        for name, args in [
            ('settings-notification-rule-create', []),
            ('settings-notifications', []),
        ]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403)

    def test_create_saves_rule_with_recipients(self):
        self.client.login(username='boss', password='x')
        team = Team.objects.create(name='Ops')
        response = self.client.post(
            reverse('settings-notification-rule-create'),
            self._post_data(users=[str(self.plain.pk)], teams=[str(team.pk)], notify_assignee='on'),
        )
        self.assertRedirects(response, reverse('settings-notifications'))
        rule = NotificationRule.objects.get()
        self.assertEqual(list(rule.users.all()), [self.plain])
        self.assertEqual(list(rule.teams.all()), [team])
        self.assertTrue(rule.notify_assignee)

    def test_invalid_json_rejected_and_text_kept(self):
        self.client.login(username='boss', password='x')
        response = self.client.post(reverse('settings-notification-rule-create'), self._post_data(filter='{bad'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '{bad')
        self.assertEqual(NotificationRule.objects.count(), 0)

    def test_unknown_op_rejected(self):
        self.client.login(username='boss', password='x')
        response = self.client.post(
            reverse('settings-notification-rule-create'),
            self._post_data(filter='{"path": "$.a", "op": "nope", "value": 1}'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(NotificationRule.objects.count(), 0)

    def test_toggle_deactivates_and_keeps_history(self):
        self.client.login(username='boss', password='x')
        rule = _make_rule()
        NotificationRuleHit.objects.create(rule=rule, issue_key='GITIN-1')
        self.client.post(reverse('settings-notification-rule-toggle', args=[rule.pk]))
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)
        self.assertEqual(rule.hits.count(), 1)

    def test_test_action_reports_match_and_writes_nothing(self):
        self.client.login(username='boss', password='x')
        rule = _make_rule()
        _make_ticket('GITIN-1', labels=[])
        _make_ticket('GITIN-2', labels=['INFRADEVOPS'])
        url = reverse('settings-notification-rule-edit', args=[rule.pk])
        self.assertContains(self.client.get(url, {'test_key': 'GITIN-1'}), 'Matches')
        self.assertContains(self.client.get(url, {'test_key': 'GITIN-2'}), 'No match')
        self.assertContains(self.client.get(url, {'test_key': 'NOPE-9'}), 'not found')
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(NotificationRuleHit.objects.count(), 0)

    def test_list_page_shows_rules(self):
        self.client.login(username='boss', password='x')
        _make_rule(name='Visible rule')
        self.assertContains(self.client.get(reverse('settings-notifications')), 'Visible rule')
