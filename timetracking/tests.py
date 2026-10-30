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

    def test_default_matches_exclusive(self):
        self.real_day_tickets()
        end = at(2, '00:00')
        response = self.report(end)
        self.assertEqual(response.context['time_mode'], 'exclusive')
        self.assertEqual(self.ip_display(response), self.ip_display(self.report(end, time='exclusive')))
        self.assertNotEqual(self.ip_display(response), self.ip_display(self.report(end, time='overlap')))

    def test_overlap_is_opt_in_and_carried_by_links(self):
        response = self.report(at(2, '00:00'), time='overlap')
        self.assertEqual(response.context['time_mode'], 'overlap')
        self.assertContains(response, '<input type="hidden" name="time" value="overlap">')
        self.assertNotContains(self.report(at(2, '00:00')), '<input type="hidden" name="time"')

    def test_overlap_counts_every_task(self):
        self.real_day_tickets()
        shown = self.ip_display(self.report(at(2, '00:00'), time='overlap'))
        self.assertEqual(shown['GITIN-2132'], '13h 52m')
        self.assertEqual(shown['GITIN-2116'], '10h 4m')

    def test_exclusive_real_data_example(self):
        self.real_day_tickets()
        shown = self.ip_display(self.report(at(2, '00:00'), time='exclusive'))
        # 2107's morning IP segment was entered on Sep 30, before the range: since v5.18.3 the
        # part inside the range counts, but a stay carried over from the previous day only counts
        # from the schedule's first working hour (09:00 here): 09:00-09:31:14 plus 13:55:00-02.
        self.assertEqual(shown['GITIN-2107'], '31m')
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
        # A was entered the day before, so it counts from the first working hour (09:00).
        self.assertEqual(self.ip_display(self.report(end, time='overlap'))['A-1'], '14h 59m')
        self.assertEqual(self.ip_display(self.report(end, time='exclusive'))['A-1'], '14h 59m')

    def test_exclusive_total_never_exceeds_elapsed(self):
        self.real_day_tickets()
        response = self.report(at(2, '00:00'), time='exclusive')
        secs = sum(t['secs'] for t in response.context['status_totals'] if t['status'] == 'In Progress')
        # 31:16 (2107, carried over: counts from 09:00) + 10:04:57 (2116) + 3:47:23 (2132).
        self.assertEqual(secs, 51816)
        self.assertLessEqual(secs, 24 * 3600)

    def test_today_panel_marks_preempted_ticket_paused(self):
        self.real_day_tickets()
        response = self.report(at(1, '15:00'), time='exclusive', range='today')
        rows = {r['ticket'].issue_key: r for r in response.context['today_rows']}
        self.assertEqual(rows['GITIN-2132']['jira_ongoing'], 'paused')
        self.assertNotEqual(rows['GITIN-2116']['jira_ongoing'], 'paused')
        # Envelope = 2116's time + 2107's exclusive time (09:00-09:31 carried over, plus 2 s).
        self.assertEqual(rows['GITIN-2116']['parent_row']['jira_today'], '1h 36m')
        self.assertEqual(rows['GITIN-2132']['jira_today'], '3h 47m')

    def tag(self, key, name):
        ticket = Ticket.objects.create(
            title='x', description='x', type='incident', external_id=key, requester=self.user,
        )
        TicketTag.objects.create(ticket=ticket, tag=Tag.objects.get_or_create(name=name)[0])

    def tag_totals(self, response):
        return {row['tag']: row for row in response.context['tag_totals']}

    def test_stay_from_before_range_ended_inside_counts_in_range_part(self):
        # Carried over from the previous day: counts from 09:00 (first working hour) to 12:00.
        self.ticket('A-1', [
            (sep(30, '22:00'), 'Backlog', 'In Progress'),
            (at(1, '12:00'), 'In Progress', 'Done'),
        ], 'Done')
        for mode in ('overlap', 'exclusive'):
            with self.subTest(mode=mode):
                shown = self.ip_display(self.report(at(2, '00:00'), time=mode))
                self.assertEqual(shown['A-1'], '3h 0m')

    def test_stay_ended_before_range_counts_zero(self):
        self.ticket('A-1', [
            (sep(29, '10:00'), 'Backlog', 'In Progress'),
            (sep(29, '12:00'), 'In Progress', 'Done'),
        ], 'Done')
        for mode in ('overlap', 'exclusive'):
            with self.subTest(mode=mode):
                response = self.report(at(2, '00:00'), time=mode)
                self.assertNotIn('A-1', [r['ticket'].issue_key for r in response.context['pivot_rows']])

    def test_tag_totals_count_ongoing_and_straddling_stays_exclusive(self):
        # A (newer) owns 00:00-12:00, then B (ongoing since Sep 30 20:00) owns the rest. Both are
        # carried over, so neither counts before 09:00: A 09-12 (3h) + B 12:00-23:59:59.
        self.ticket('A-1', [
            (sep(30, '22:00'), 'Backlog', 'In Progress'),
            (at(1, '12:00'), 'In Progress', 'Done'),
        ], 'Done')
        self.ticket('B-1', [(sep(30, '20:00'), 'Backlog', 'In Progress')], 'In Progress')
        self.tag('A-1', 'SmartPedidos')
        self.tag('B-1', 'SmartPedidos')
        row = self.tag_totals(self.report(at(2, '00:00'), time='exclusive'))['SmartPedidos']
        # The custom one-day range ends at 23:59:59.
        self.assertEqual(row['secs'], 15 * 3600 - 1)
        # Labor 09:00-18:00 on a Thursday: A 09-12 plus B 12-18.
        self.assertEqual(row['labor_secs'], 9 * 3600)

    def test_tag_totals_overlap_counts_each_ticket_wall_clock(self):
        self.ticket('A-1', [
            (sep(30, '22:00'), 'Backlog', 'In Progress'),
            (at(1, '12:00'), 'In Progress', 'Done'),
        ], 'Done')
        self.ticket('B-1', [(sep(30, '20:00'), 'Backlog', 'In Progress')], 'In Progress')
        self.tag('A-1', 'SmartPedidos')
        self.tag('B-1', 'SmartPedidos')
        row = self.tag_totals(self.report(at(2, '00:00'), time='overlap'))['SmartPedidos']
        # A 09:00-12:00 (3h) + B 09:00-23:59:59, both carried over from the previous day.
        self.assertEqual(row['secs'], 18 * 3600 - 1)

    def test_carried_over_stay_does_not_count_before_first_working_hour(self):
        # Forgotten In Progress overnight: 00:00-09:00 does not count, same-day entries do.
        self.ticket('A-1', [(sep(30, '22:00'), 'Backlog', 'In Progress')], 'In Progress')
        self.ticket('B-1', [(at(1, '07:00'), 'Backlog', 'In Progress')], 'In Progress')
        for mode in ('overlap',):
            shown = self.ip_display(self.report(at(2, '00:00'), time=mode))
            self.assertEqual(shown['A-1'], '14h 59m')
            self.assertEqual(shown['B-1'], '16h 59m')

    def test_carried_over_stay_counts_nothing_on_a_non_working_day(self):
        # Oct 3 2026 is a Saturday.
        self.ticket('A-1', [
            (at(2, '20:00'), 'Backlog', 'In Progress'),
            (at(3, '12:00'), 'In Progress', 'Done'),
        ], 'Done')
        for mode in ('overlap', 'exclusive'):
            with self.subTest(mode=mode):
                response = self.report(at(4, '00:00'), time=mode, date_from='2026-10-03', date_to='2026-10-03')
                self.assertNotIn('A-1', [r['ticket'].issue_key for r in response.context['pivot_rows']])

    def test_tag_totals_overlap_counts_parent_and_child_once(self):
        # P (parent) 08:00-12:00 and its subtask C 09:00-11:00 carry the same tag.
        self.ticket('P-1', [
            (at(1, '08:00'), 'Backlog', 'In Progress'),
            (at(1, '12:00'), 'In Progress', 'Done'),
        ], 'Done')
        self.ticket('C-1', [
            (at(1, '09:00'), 'Backlog', 'In Progress'),
            (at(1, '11:00'), 'In Progress', 'Done'),
        ], 'Done', parent='P-1')
        self.tag('P-1', 'SmartPedidos')
        self.tag('C-1', 'SmartPedidos')
        for mode in ('overlap', 'exclusive'):
            with self.subTest(mode=mode):
                row = self.tag_totals(self.report(at(2, '00:00'), time=mode))['SmartPedidos']
                # C 2h + P only while C was not IP (08-09, 11-12) = 4h, not 6h.
                self.assertEqual(row['secs'], 4 * 3600)
                # Labor 09:00-18:00: C 2h + P 11:00-12:00 = 3h.
                self.assertEqual(row['labor_secs'], 3 * 3600)

    def test_tag_total_matches_pivot_for_same_ticket(self):
        self.ticket('A-1', [
            (sep(30, '22:00'), 'Backlog', 'In Progress'),
            (at(1, '12:00'), 'In Progress', 'Done'),
        ], 'Done')
        self.tag('A-1', 'Concentrador')
        response = self.report(at(2, '00:00'), time='exclusive')
        self.assertEqual(self.tag_totals(response)['Concentrador']['display'], '3h 0m')
        self.assertEqual(self.ip_display(response)['A-1'], '3h 0m')


# ---------------------------------------------------------------------------
# In Progress map (v5.18.0)
# ---------------------------------------------------------------------------

import zoneinfo
from collections import namedtuple

from itsm.models import Tag, Ticket, TicketTag
from settings_hub.models import AppSetting, JiraStatusConfig
from timetracking import ip_map

FakeTicket = namedtuple('FakeTicket', 'issue_key title parent_key labels')
IP_CATEGORIES = {
    'in progress': 'in_progress', 'en curso': 'in_progress', 'bloqueado': 'blocked',
    'testing': 'testing', 'done': 'done', 'descartado': 'done',
    'backlog': 'backlog', 'selected for development': 'other',
}


def ft(key, parent='', labels=None):
    return FakeTicket(key, f'Title {key}', parent, labels or [])


def tr(when, from_status, to_status):
    return {'at': when, 'from_status': from_status, 'to_status': to_status}


def build(tickets, transitions, start=None, end=None, tz=UTC, visible=None, working_seconds=None):
    start = start or at(1, '00:00')
    end = end or at(31, '23:59')
    return ip_map.build_ip_map(
        tickets, transitions, IP_CATEGORIES, start, end, tz, visible_keys=visible,
        working_seconds=working_seconds,
    )


class IpMapEntryTests(TestCase):
    def test_first_entry_is_created_and_destination_done(self):
        t = ft('G-1')
        data = build([t], {'G-1': [
            tr(at(5, '10:00'), 'Backlog', 'In Progress'),
            tr(at(5, '12:00'), 'In Progress', 'Done'),
        ]})
        card = data['days'][0]['cards'][0]
        self.assertEqual((card['origin'], card['dest']), ('created', 'done'))
        self.assertEqual(data['summary']['entries'], 1)

    def test_en_curso_duplicate_is_same_stay(self):
        t = ft('G-1')
        data = build([t], {'G-1': [
            tr(at(5, '10:00'), 'Backlog', 'In Progress'),
            tr(at(5, '10:01'), 'In Progress', 'En curso'),
            tr(at(5, '12:00'), 'En curso', 'Bloqueado'),
        ]})
        self.assertEqual(data['summary']['entries'], 1)
        self.assertEqual(data['days'][0]['cards'][0]['dest'], 'blocked')

    def test_still_in_progress(self):
        data = build([ft('G-1')], {'G-1': [tr(at(5, '10:00'), 'Backlog', 'In Progress')]})
        self.assertEqual(data['days'][0]['cards'][0]['dest'], 'ip')

    def test_origins_blocked_testing_queue_done(self):
        t = ft('G-1')
        history = [
            tr(at(5, '09:00'), 'Backlog', 'In Progress'),
            tr(at(5, '10:00'), 'In Progress', 'Bloqueado'),
            tr(at(5, '11:00'), 'Bloqueado', 'In Progress'),
            tr(at(5, '12:00'), 'In Progress', 'Testing'),
            tr(at(5, '13:00'), 'Testing', 'In Progress'),
            tr(at(5, '14:00'), 'In Progress', 'Selected for Development'),
            tr(at(5, '15:00'), 'Selected for Development', 'In Progress'),
            tr(at(5, '16:00'), 'In Progress', 'Done'),
            tr(at(6, '09:00'), 'Done', 'In Progress'),
        ]
        entries = ip_map.collect_entries([t], {'G-1': history}, IP_CATEGORIES, at(31, '00:00'))
        self.assertEqual(
            [e['origin'] for e in entries], ['created', 'blocked', 'testing', 'queue', 'done'],
        )
        self.assertEqual(
            [e['dest'] for e in entries], ['blocked', 'testing', 'queue', 'done', 'ip'],
        )

    def test_created_even_when_first_entry_is_before_range(self):
        t = ft('G-1')
        history = [
            tr(at(1, '09:00'), 'Backlog', 'In Progress'),
            tr(at(1, '10:00'), 'In Progress', 'Bloqueado'),
            tr(at(8, '09:00'), 'Bloqueado', 'In Progress'),
        ]
        data = build([t], {'G-1': history}, start=at(8, '00:00'))
        self.assertEqual(data['summary']['entries'], 1)
        self.assertEqual(data['days'][0]['cards'][0]['origin'], 'blocked')

    def test_entries_outside_range_are_excluded(self):
        t = ft('G-1')
        data = build([t], {'G-1': [tr(at(5, '10:00'), 'Backlog', 'In Progress')]}, start=at(6, '00:00'))
        self.assertEqual(data['days'], [])
        self.assertEqual(data['summary']['entries'], 0)


class IpMapParentCollapseTests(TestCase):
    def setUp(self):
        self.parent = ft('G-P')
        self.child = ft('G-C', parent='G-P')

    def test_parent_dropped_when_child_enters_within_window_either_order(self):
        for parent_at, child_at in [(at(5, '10:00:00'), at(5, '10:00:30')),
                                    (at(5, '10:00:30'), at(5, '10:00:00'))]:
            data = build([self.parent, self.child], {
                'G-P': [tr(parent_at, 'Backlog', 'In Progress')],
                'G-C': [tr(child_at, 'Backlog', 'In Progress')],
            })
            keys = [c['key'] for c in data['days'][0]['cards']]
            self.assertEqual(keys, ['G-C'])

    def test_parent_kept_outside_window(self):
        data = build([self.parent, self.child], {
            'G-P': [tr(at(5, '10:00:00'), 'Backlog', 'In Progress')],
            'G-C': [tr(at(5, '10:05:00'), 'Backlog', 'In Progress')],
        })
        self.assertEqual([c['key'] for c in data['days'][0]['cards']], ['G-P', 'G-C'])

    def test_parent_without_child_entry_kept(self):
        data = build([self.parent, self.child], {
            'G-P': [tr(at(5, '10:00:00'), 'Backlog', 'In Progress')],
            'G-C': [],
        })
        self.assertEqual([c['key'] for c in data['days'][0]['cards']], ['G-P'])


class IpMapGroupingTests(TestCase):
    def test_consecutive_reentries_collapse_with_repeat(self):
        t = ft('G-1')
        data = build([t], {'G-1': [
            tr(at(5, '09:00'), 'Backlog', 'In Progress'),
            tr(at(5, '10:00'), 'In Progress', 'Selected for Development'),
            tr(at(5, '11:00'), 'Selected for Development', 'In Progress'),
            tr(at(5, '12:00'), 'In Progress', 'Done'),
        ]})
        cards = data['days'][0]['cards']
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['repeat'], 2)
        self.assertEqual((cards[0]['origin'], cards[0]['dest']), ('created', 'done'))
        self.assertEqual(data['days'][0]['count'], 2)

    def test_returning_after_other_ticket_gets_own_card(self):
        a, b = ft('G-A'), ft('G-B')
        data = build([a, b], {
            'G-A': [tr(at(5, '09:00'), 'Backlog', 'In Progress'),
                    tr(at(5, '09:30'), 'In Progress', 'Bloqueado'),
                    tr(at(5, '11:00'), 'Bloqueado', 'In Progress')],
            'G-B': [tr(at(5, '10:00'), 'Backlog', 'In Progress')],
        })
        self.assertEqual([c['key'] for c in data['days'][0]['cards']], ['G-A', 'G-B', 'G-A'])

    def test_days_use_viewer_timezone_around_midnight(self):
        cordoba = zoneinfo.ZoneInfo('America/Argentina/Cordoba')  # UTC-3
        t = ft('G-1')
        data = build([t], {'G-1': [tr(at(6, '01:30'), 'Backlog', 'In Progress')]}, tz=cordoba)
        self.assertEqual(data['days'][0]['date'], dt.date(2026, 10, 5))

    def test_days_newest_first_chain_oldest_first(self):
        a, b, c = ft('G-A'), ft('G-B'), ft('G-C')
        data = build([a, b, c], {
            'G-A': [tr(at(5, '09:00'), 'Backlog', 'In Progress')],
            'G-B': [tr(at(6, '09:00'), 'Backlog', 'In Progress')],
            'G-C': [tr(at(6, '10:00'), 'Backlog', 'In Progress')],
        })
        self.assertEqual([d['date'] for d in data['days']], [dt.date(2026, 10, 6), dt.date(2026, 10, 5)])
        self.assertEqual([c['key'] for c in data['days'][0]['cards']], ['G-B', 'G-C'])
        self.assertLess(data['mermaid'].index('G-B'), data['mermaid'].index('G-A'))

    def test_visible_keys_restricts_cards_but_not_collapse(self):
        a, b = ft('G-A'), ft('G-B')
        data = build([a, b], {
            'G-A': [tr(at(5, '09:00'), 'Backlog', 'In Progress')],
            'G-B': [tr(at(5, '10:00'), 'Backlog', 'In Progress')],
        }, visible={'G-B'})
        self.assertEqual([c['key'] for c in data['days'][0]['cards']], ['G-B'])
        self.assertEqual(data['summary']['entries'], 1)

    def test_mermaid_text(self):
        a, b = ft('G-A'), ft('G-B')
        data = build([a, b], {
            'G-A': [tr(at(5, '09:00'), 'Backlog', 'In Progress'), tr(at(5, '09:30'), 'In Progress', 'Done')],
            'G-B': [tr(at(5, '10:00'), 'Backlog', 'In Progress')],
        })
        text = data['mermaid']
        self.assertIn('flowchart LR', text)
        self.assertIn('n0["G-A ✚→✔"]', text)
        self.assertIn('n1["G-B ✚→▶"]', text)
        self.assertIn('n0 --> n1', text)

    def test_mermaid_sanitises_keys(self):
        t = ft('G-1"]; x["')
        data = build([t], {t.issue_key: [tr(at(5, '09:00'), 'Backlog', 'In Progress')]})
        self.assertNotIn('"]; x', data['mermaid'])


class IpMapCardTimeTests(TestCase):
    @staticmethod
    def half(start, end):
        # Fake schedule clipper: counts half of the stay.
        return int((end - start).total_seconds()) // 2

    def test_total_and_working_time_per_card(self):
        t = ft('G-1')
        data = build([t], {'G-1': [
            tr(at(5, '09:00'), 'Backlog', 'In Progress'),
            tr(at(5, '11:00'), 'In Progress', 'Done'),
        ]}, working_seconds=self.half)
        card = data['days'][0]['cards'][0]
        self.assertEqual((card['total_secs'], card['wh_secs']), (7200, 3600))
        self.assertEqual((card['total_label'], card['wh_label']), ('2h 0m', '1h 0m'))
        self.assertTrue(data['has_wh'])

    def test_merged_card_sums_both_times(self):
        t = ft('G-1')
        data = build([t], {'G-1': [
            tr(at(5, '09:00'), 'Backlog', 'In Progress'),
            tr(at(5, '10:00'), 'In Progress', 'Selected for Development'),
            tr(at(5, '11:00'), 'Selected for Development', 'In Progress'),
            tr(at(5, '12:00'), 'In Progress', 'Done'),
        ]}, working_seconds=self.half)
        card = data['days'][0]['cards'][0]
        self.assertEqual(card['repeat'], 2)
        self.assertEqual((card['total_secs'], card['wh_secs']), (7200, 3600))

    def test_still_in_progress_counts_up_to_end(self):
        t = ft('G-1')
        data = build([t], {'G-1': [tr(at(5, '09:00'), 'Backlog', 'In Progress')]},
                     end=at(5, '09:40'), working_seconds=self.half)
        card = data['days'][0]['cards'][0]
        self.assertEqual((card['dest'], card['total_label']), ('ip', '40m'))

    def test_no_clipper_means_no_working_time(self):
        t = ft('G-1')
        data = build([t], {'G-1': [tr(at(5, '09:00'), 'Backlog', 'In Progress')]})
        card = data['days'][0]['cards'][0]
        self.assertIsNone(card['wh_secs'])
        self.assertEqual(card['wh_label'], '—')
        self.assertFalse(data['has_wh'])


class IpMapViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('agent', password='pass')
        UserProfile.objects.update_or_create(user=self.user, defaults={'jira_account_id': ACCOUNT_ID})
        WorkSchedule.objects.update_or_create(user=self.user, defaults={'timezone': 'UTC'})
        for name, cat in [('In Progress', 'in_progress'), ('Done', 'done'), ('Bloqueado', 'blocked')]:
            JiraStatusConfig.objects.update_or_create(status_name=name, defaults={'category': cat})
        self.client.force_login(self.user)
        self.url = reverse('timetracking-report')

    def ticket(self, key, transitions, status, labels=None):
        ticket = JiraTicket.objects.create(
            issue_key=key, title=f'Title {key}', status=status, labels=labels or [],
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

    def report(self, **params):
        params.setdefault('range', 'custom')
        params.setdefault('date_from', '2026-10-01')
        params.setdefault('date_to', '2026-10-01')
        with mock.patch('django.utils.timezone.now', return_value=at(2, '12:00')):
            response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        return response

    def seed(self):
        self.ticket('GITIN-1', [
            (at(1, '09:00'), 'Backlog', 'In Progress'),
            (at(1, '11:00'), 'In Progress', 'Done'),
        ], 'Done', labels=['INFRADEVOPS', 'SRE', 'A', 'B'])
        self.ticket('GITIN-2', [(at(1, '10:00'), 'Backlog', 'In Progress')], 'In Progress')

    def test_context_and_card_rendered(self):
        self.seed()
        response = self.report()
        days = response.context['ip_map_days']
        self.assertEqual([c['key'] for c in days[0]['cards']], ['GITIN-1', 'GITIN-2'])
        self.assertEqual(response.context['ip_map_summary']['entries'], 2)
        self.assertContains(response, 'In Progress map')
        self.assertContains(response, reverse('timetracking-ticket-timeline', args=['GITIN-1']))
        self.assertContains(response, 'Copy as Mermaid')

    def test_card_time_total_and_working_hours(self):
        self.ticket('GITIN-1', [
            (at(1, '08:00'), 'Backlog', 'In Progress'),
            (at(1, '10:00'), 'In Progress', 'Done'),
        ], 'Done')
        WorkSchedule.objects.filter(user=self.user).update(
            start_time=dt.time(9, 0), end_time=dt.time(18, 0), thu=True,
        )
        response = self.report()
        card = response.context['ip_map_days'][0]['cards'][0]
        self.assertEqual((card['total_label'], card['wh_label']), ('2h 0m', '1h 0m'))
        self.assertTrue(response.context['ip_map_has_wh'])
        self.assertNotContains(response, 'No working schedule set')

    def test_jira_link_only_with_base_url(self):
        self.seed()
        self.assertNotContains(self.report(), '/browse/GITIN-1')
        AppSetting.objects.create(key='jira_base_url', value='https://x.atlassian.net/')
        self.assertContains(self.report(), 'https://x.atlassian.net/browse/GITIN-1')

    def test_empty_range_shows_empty_state(self):
        response = self.report(date_from='2026-09-01', date_to='2026-09-01')
        self.assertContains(response, 'No tickets were put into In Progress in this range.')
        self.assertNotContains(response, 'Copy as Mermaid')

    def test_time_and_labor_toggles_do_not_change_map(self):
        self.seed()
        base = self.report().context['ip_map_summary']
        self.assertEqual(self.report(time='exclusive').context['ip_map_summary'], base)

    def test_tag_filter_limits_tickets_status_filter_does_not(self):
        self.seed()
        tag = Tag.objects.create(name='INFRADEVOPS')
        ticket = Ticket.objects.create(
            title='x', description='x', type='incident', external_id='GITIN-1', requester=self.user,
        )
        TicketTag.objects.create(ticket=ticket, tag=tag)
        filtered = self.report(tags='INFRADEVOPS').context['ip_map_summary']
        self.assertEqual(filtered['tickets'], 1)
        status_filtered = self.report(statuses='Bloqueado').context['ip_map_summary']
        self.assertEqual(status_filtered['entries'], 2)

    def test_more_than_four_cards_renders_mobile_collapse(self):
        for i in range(6):
            self.ticket(f'GITIN-{10 + i}', [(at(1, f'0{i + 1}:00'), 'Backlog', 'In Progress')], 'In Progress')
        response = self.report()
        self.assertContains(response, 'ipm-more')
        self.assertContains(response, 'Show 2 more')
