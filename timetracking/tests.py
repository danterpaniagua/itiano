import datetime as dt
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import UserProfile
from jira_integration.models import JiraEvent, JiraTicket
from timetracking.models import WorkSchedule

UTC = dt.timezone.utc
ACCOUNT_ID = 'acc-1'


def at(day, hhmmss, month=10):
    parts = [int(p) for p in hhmmss.split(':')]
    while len(parts) < 3:
        parts.append(0)
    return dt.datetime(2026, month, day, *parts, tzinfo=UTC)


def sep(day, hhmmss):
    return at(day, hhmmss, month=9)


class ExclusiveTimeReportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('agent', password='pass')
        UserProfile.objects.update_or_create(user=self.user, defaults={'jira_account_id': ACCOUNT_ID})
        WorkSchedule.objects.update_or_create(user=self.user, defaults={'timezone': 'UTC'})
        self.client.force_login(self.user)
        self.url = reverse('timetracking-report')

    def ticket(self, key, transitions, status, parent=''):
        """transitions: [(received_at, from_status, to_status), ...]"""
        ticket = JiraTicket.objects.create(
            issue_key=key, title=key, status=status, parent_key=parent,
            assignee='Agent', assignee_account_id=ACCOUNT_ID,
        )
        for received_at, from_status, to_status in transitions:
            JiraEvent.objects.create(
                ticket=ticket, event_type='jira:issue_updated', received_at=received_at,
                payload={'changelog': {'items': [
                    {'field': 'status', 'fromString': from_status, 'toString': to_status},
                ]}},
            )
        return ticket

    def report(self, now, time=None, **params):
        params.setdefault('range', 'custom')
        params.setdefault('date_from', '2026-10-01')
        params.setdefault('date_to', '2026-10-01')
        if time:
            params['time'] = time
        with mock.patch('django.utils.timezone.now', return_value=now):
            response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        return response

    def ip_display(self, response):
        """{issue_key: 'In Progress' cell duration} from the status pivot."""
        index = response.context['all_statuses'].index('In Progress')
        return {
            row['ticket'].issue_key: row['cells'][index]['duration']
            for row in response.context['pivot_rows']
        }

    def real_day_tickets(self):
        # GITIN-2107 / 2116 / 2132 on 2026-10-01 (2116 is a child of 2107).
        self.ticket('GITIN-2107', [
            (sep(30, '18:13:32'), 'Bloqueado', 'In Progress'),
            (at(1, '09:31:14'), 'In Progress', 'Bloqueado'),
            (at(1, '13:55:00'), 'Bloqueado', 'In Progress'),
        ], 'In Progress')
        self.ticket('GITIN-2116', [
            (sep(30, '18:13:29'), 'Bloqueado', 'Testing'),
            (at(1, '09:31:16'), 'Testing', 'Bloqueado'),
            (at(1, '13:55:02'), 'Bloqueado', 'In Progress'),
        ], 'In Progress', parent='GITIN-2107')
        self.ticket('GITIN-2132', [
            (at(1, '10:07:37'), 'Selected for Development', 'In Progress'),
        ], 'In Progress')

    def test_default_matches_overlap(self):
        self.real_day_tickets()
        end = at(2, '00:00')
        self.assertEqual(
            self.ip_display(self.report(end)),
            self.ip_display(self.report(end, time='overlap')),
        )

    def test_overlap_counts_every_task(self):
        self.real_day_tickets()
        shown = self.ip_display(self.report(at(2, '00:00'), time='overlap'))
        self.assertEqual(shown['GITIN-2132'], '13h 52m')
        self.assertEqual(shown['GITIN-2116'], '10h 4m')

    def test_exclusive_real_data_example(self):
        self.real_day_tickets()
        shown = self.ip_display(self.report(at(2, '00:00'), time='exclusive'))
        # 2107's morning IP segment was entered on Sep 30, before the range, and has already
        # ended: the existing range rule only credits segments ENTERED inside the range (plus
        # ongoing ones), so only its 13:55:00-13:55:02 slice counts here.
        self.assertEqual(shown['GITIN-2107'], '0m')
        self.assertEqual(shown['GITIN-2116'], '10h 4m')
        self.assertEqual(shown['GITIN-2132'], '3h 47m')

    def test_stack_resume_and_parent_yields_to_preempted_child(self):
        # P (parent) 09:00-13:00; C1 (child of P) 09:01-12:00; X (unrelated) 10:00-11:00.
        self.ticket('P-1', [
            (at(1, '09:00'), 'Backlog', 'In Progress'),
            (at(1, '13:00'), 'In Progress', 'Bloqueado'),
        ], 'Bloqueado')
        self.ticket('C-1', [
            (at(1, '09:01'), 'Backlog', 'In Progress'),
            (at(1, '12:00'), 'In Progress', 'Bloqueado'),
        ], 'Bloqueado', parent='P-1')
        self.ticket('X-1', [
            (at(1, '10:00'), 'Backlog', 'In Progress'),
            (at(1, '11:00'), 'In Progress', 'Bloqueado'),
        ], 'Bloqueado')
        shown = self.ip_display(self.report(at(2, '00:00'), time='exclusive'))
        # P: 09:00-09:01 + 12:00-13:00; C1: 09:01-10:00 + 11:00-12:00; X: 10:00-11:00.
        self.assertEqual(shown['P-1'], '1h 1m')
        self.assertEqual(shown['C-1'], '1h 59m')
        self.assertEqual(shown['X-1'], '1h 0m')

    def test_child_outside_in_progress_does_not_suppress_parent(self):
        self.ticket('P-1', [(at(1, '09:00'), 'Backlog', 'In Progress')], 'In Progress')
        self.ticket('C-1', [
            (at(1, '08:00'), 'Backlog', 'Testing'),
        ], 'Testing', parent='P-1')
        shown = self.ip_display(self.report(at(1, '12:00'), time='exclusive', range='today'))
        self.assertEqual(shown['P-1'], '3h 0m')

    def test_preempting_segment_from_before_the_range_still_preempts(self):
        # A is IP since the day before and still ongoing; B entered IP even earlier-than-range
        # but later than A, and leaves at 02:00 inside the range.
        self.ticket('A-1', [(sep(30, '22:00'), 'Backlog', 'In Progress')], 'In Progress')
        self.ticket('B-1', [
            (sep(30, '23:00'), 'Backlog', 'In Progress'),
            (at(1, '02:00'), 'In Progress', 'Bloqueado'),
        ], 'Bloqueado')
        end = at(2, '00:00')
        self.assertEqual(self.ip_display(self.report(end, time='overlap'))['A-1'], '23h 59m')
        self.assertEqual(self.ip_display(self.report(end, time='exclusive'))['A-1'], '21h 59m')

    def test_exclusive_total_never_exceeds_elapsed(self):
        self.real_day_tickets()
        response = self.report(at(2, '00:00'), time='exclusive')
        secs = sum(t['secs'] for t in response.context['status_totals'] if t['status'] == 'In Progress')
        # 2s (2107) + 10:04:57 (2116) + 3:47:23 (2132); never more than the day itself.
        self.assertEqual(secs, 49942)
        self.assertLessEqual(secs, 24 * 3600)

    def test_today_panel_marks_preempted_ticket_paused(self):
        self.real_day_tickets()
        response = self.report(at(1, '15:00'), time='exclusive', range='today')
        rows = {r['ticket'].issue_key: r for r in response.context['today_rows']}
        self.assertEqual(rows['GITIN-2132']['jira_ongoing'], 'paused')
        self.assertNotEqual(rows['GITIN-2116']['jira_ongoing'], 'paused')
        # Envelope = 2116's time + 2107's exclusive time (9h31m of "today" before 13:55).
        self.assertEqual(rows['GITIN-2116']['parent_row']['jira_today'], '10h 36m')
        self.assertEqual(rows['GITIN-2132']['jira_today'], '3h 47m')
