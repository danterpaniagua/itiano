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

    def test_focus_map_matches_the_exclusive_report(self):
        # Parity: the map's owned time per ticket equals the report's Exclusive In Progress time.
        from collections import defaultdict
        self.real_day_tickets()
        end = at(2, '00:00')
        report = self.report(end, time='exclusive')
        report_secs = sum(t['secs'] for t in report.context['status_totals'] if t['status'] == 'In Progress')
        with mock.patch('django.utils.timezone.now', return_value=end):
            page = self.client.get(reverse('timetracking-map'), {
                'range': 'custom', 'date_from': '2026-10-01', 'date_to': '2026-10-01',
            })
        self.assertEqual(page.status_code, 200)
        per_ticket = defaultdict(int)
        for day in page.context['focus_days']:
            for card in day['cards']:
                per_ticket[card['key']] += card['secs']
        self.assertEqual(sum(per_ticket.values()), report_secs)
        shown = self.ip_display(report)
        for key, secs in per_ticket.items():
            expected = f'{secs // 3600}h {secs % 3600 // 60}m' if secs >= 3600 else f'{secs // 60}m'
            self.assertEqual(shown[key], expected, key)

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
                # The ticket may still show up (its Done status entered inside the range), but it
                # has no In Progress time.
                ip_secs = sum(t['secs'] for t in response.context['status_totals'] if t['status'] == 'In Progress')
                self.assertEqual(ip_secs, 0)

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


class MapPageMixin:
    """Shared setup for the /time/map/ page tests."""

    def setUp(self):
        self.user = User.objects.create_user('agent', password='pass')
        UserProfile.objects.update_or_create(user=self.user, defaults={'jira_account_id': ACCOUNT_ID})
        WorkSchedule.objects.update_or_create(user=self.user, defaults={'timezone': 'UTC'})
        for name, cat in [('In Progress', 'in_progress'), ('Done', 'done'), ('Bloqueado', 'blocked')]:
            JiraStatusConfig.objects.update_or_create(status_name=name, defaults={'category': cat})
        self.client.force_login(self.user)
        self.url = reverse('timetracking-map')

    def ticket(self, key, transitions, status, labels=None, parent=''):
        ticket = JiraTicket.objects.create(
            issue_key=key, title=f'Title {key}', status=status, labels=labels or [], parent_key=parent,
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

    def page(self, **params):
        params.setdefault('range', 'custom')
        params.setdefault('date_from', '01/Oct/2026')
        params.setdefault('date_to', '01/Oct/2026')
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


class IpMapViewTests(MapPageMixin, TestCase):
    """The entries map (Overlap view of /time/map/)."""

    def page(self, **params):
        params.setdefault('time', 'overlap')
        return super().page(**params)

    def test_context_and_card_rendered(self):
        self.seed()
        response = self.page()
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
        response = self.page()
        card = response.context['ip_map_days'][0]['cards'][0]
        self.assertEqual((card['total_label'], card['wh_label']), ('2h 0m', '1h 0m'))
        self.assertTrue(response.context['ip_map_has_wh'])
        self.assertNotContains(response, 'No working schedule set')

    def test_jira_link_only_with_base_url(self):
        self.seed()
        self.assertNotContains(self.page(), '/browse/GITIN-1')
        AppSetting.objects.create(key='jira_base_url', value='https://x.atlassian.net/')
        self.assertContains(self.page(), 'https://x.atlassian.net/browse/GITIN-1')

    def test_empty_range_shows_empty_state(self):
        response = self.page(date_from='01/Sep/2026', date_to='01/Sep/2026')
        self.assertContains(response, 'No tickets were put into In Progress in this range.')
        self.assertNotContains(response, 'Copy as Mermaid')

    def test_tag_filter_uses_labels(self):
        self.seed()
        filtered = self.page(tags='INFRADEVOPS').context['ip_map_summary']
        self.assertEqual(filtered['tickets'], 1)
        self.assertEqual(self.page().context['ip_map_summary']['tickets'], 2)

    def test_more_than_four_cards_renders_mobile_collapse(self):
        for i in range(6):
            self.ticket(f'GITIN-{10 + i}', [(at(1, f'0{i + 1}:00'), 'Backlog', 'In Progress')], 'In Progress')
        response = self.page()
        self.assertContains(response, 'ipm-more')
        self.assertContains(response, 'Show 2 more')


# ---------------------------------------------------------------------------
# In Progress map: Exclusive chain page (v5.18.4)
# ---------------------------------------------------------------------------

from timetracking import focus_map
from timetracking.map_views import format_map_date, parse_map_date


def focus(tickets, transitions, start=None, end=None, now=None, visible=None, parent_titles=None,
          subs_total=None, tz=UTC, schedule=None):
    schedule = schedule or WorkSchedule(start_time=dt.time(9, 0), end_time=dt.time(18, 0))
    return focus_map.build_focus_map(
        tickets, transitions, IP_CATEGORIES, schedule, tz,
        start or at(1, '00:00'), end or at(1, '23:59:59'), now or at(2, '00:00'),
        visible_keys=visible, parent_titles=parent_titles, subs_total=subs_total,
    )


class FocusMapChainTests(TestCase):
    def test_chain_follows_the_focus_and_resumes_the_previous_ticket(self):
        a, b = ft('G-A'), ft('G-B')
        data = focus([a, b], {
            'G-A': [tr(at(1, '09:00'), 'Backlog', 'In Progress'), tr(at(1, '12:00'), 'In Progress', 'Done')],
            'G-B': [tr(at(1, '10:00'), 'Backlog', 'In Progress'), tr(at(1, '11:00'), 'In Progress', 'Done')],
        })
        cards = data['days'][0]['cards']
        self.assertEqual([c['key'] for c in cards], ['G-A', 'G-B', 'G-A'])
        self.assertEqual([c['n'] for c in cards], [1, 2, 3])
        self.assertEqual([c['resumed'] for c in cards], [False, False, True])
        self.assertEqual([c['paused'] for c in cards], [True, False, False])
        self.assertEqual([c['dest'] for c in cards], ['ip', 'done', 'done'])

    def test_short_return_is_folded_into_the_ticket_card(self):
        a, b, d = ft('G-A'), ft('G-B'), ft('G-D')
        data = focus([a, b, d], {
            'G-A': [tr(at(1, '09:00'), 'Backlog', 'In Progress'), tr(at(1, '12:00'), 'In Progress', 'Done')],
            'G-B': [tr(at(1, '10:00'), 'Backlog', 'In Progress'), tr(at(1, '10:30'), 'In Progress', 'Done')],
            'G-D': [tr(at(1, '10:30:20'), 'Backlog', 'In Progress'), tr(at(1, '10:45'), 'In Progress', 'Done')],
        })
        cards = data['days'][0]['cards']
        self.assertEqual([c['key'] for c in cards], ['G-A', 'G-B', 'G-D', 'G-A'])
        self.assertEqual(cards[0]['secs'], 3600 + 20)
        self.assertEqual(cards[0]['folded'], '1 short return (20 s) folded')

    def test_parent_yields_to_its_active_child(self):
        p, c = ft('G-P'), ft('G-C', parent='G-P')
        data = focus([p, c], {
            'G-P': [tr(at(1, '09:00'), 'Backlog', 'In Progress'), tr(at(1, '11:00'), 'In Progress', 'Done')],
            'G-C': [tr(at(1, '09:01'), 'Backlog', 'In Progress'), tr(at(1, '10:00'), 'In Progress', 'Done')],
        })
        cards = data['days'][0]['cards']
        self.assertEqual([c['key'] for c in cards], ['G-P', 'G-C', 'G-P'])
        self.assertEqual(cards[0]['secs'], 60)
        self.assertEqual(cards[1]['secs'], 59 * 60)

    def test_total_and_working_hours_labels(self):
        t = ft('G-1')
        data = focus([t], {'G-1': [
            tr(at(1, '08:00'), 'Backlog', 'In Progress'), tr(at(1, '10:00'), 'In Progress', 'Done'),
        ]})
        card = data['days'][0]['cards'][0]
        self.assertEqual((card['total_label'], card['wh_label']), ('2h 0m', '1h 0m'))
        self.assertEqual((card['start'], card['end']), ('08:00', '10:00'))

    def test_days_newest_first(self):
        a, b = ft('G-A'), ft('G-B')
        data = focus([a, b], {
            'G-A': [tr(at(1, '09:00'), 'Backlog', 'In Progress'), tr(at(1, '10:00'), 'In Progress', 'Done')],
            'G-B': [tr(at(2, '09:00'), 'Backlog', 'In Progress'), tr(at(2, '10:00'), 'In Progress', 'Done')],
        }, end=at(2, '23:59:59'), now=at(3, '00:00'))
        self.assertEqual([d['date'] for d in data['days']], [dt.date(2026, 10, 2), dt.date(2026, 10, 1)])

    def test_tag_filter_hides_cards_without_changing_owned_time(self):
        a, b = ft('G-A'), ft('G-B')
        transitions = {
            'G-A': [tr(at(1, '09:00'), 'Backlog', 'In Progress'), tr(at(1, '12:00'), 'In Progress', 'Done')],
            'G-B': [tr(at(1, '10:00'), 'Backlog', 'In Progress'), tr(at(1, '11:00'), 'In Progress', 'Done')],
        }
        everything = focus([a, b], transitions)['days'][0]['cards']
        only_a = focus([a, b], transitions, visible={'G-A'})['days'][0]['cards']
        self.assertEqual([c['key'] for c in only_a], ['G-A', 'G-A'])
        self.assertEqual(
            sum(c['secs'] for c in only_a),
            sum(c['secs'] for c in everything if c['key'] == 'G-A'),
        )


class FocusMapCarryOverTests(TestCase):
    def test_carried_over_ticket_restarts_at_the_first_working_hour(self):
        a = ft('G-A')
        data = focus([a], {'G-A': [tr(sep(30, '22:00'), 'Backlog', 'In Progress')]})
        card = data['days'][0]['cards'][0]
        self.assertEqual(card['start'], '09:00')
        self.assertEqual(card['since'], 'Wed 30/09 22:00')
        self.assertTrue(card['running'])
        self.assertEqual(card['secs'], 15 * 3600 - 1)

    def test_same_day_entry_before_the_first_working_hour_counts_from_entry(self):
        b = ft('G-B')
        data = focus([b], {'G-B': [tr(at(1, '07:00'), 'Backlog', 'In Progress')]})
        card = data['days'][0]['cards'][0]
        self.assertEqual((card['start'], card['since']), ('07:00', ''))

    def test_carried_over_ticket_shows_nothing_on_a_non_working_day(self):
        a = ft('G-A')
        # Oct 3 2026 is a Saturday.
        data = focus([a], {'G-A': [tr(at(2, '20:00'), 'Backlog', 'In Progress')]},
                     start=at(3, '00:00'), end=at(3, '23:59:59'), now=at(4, '00:00'))
        self.assertEqual(data['days'], [])
        self.assertEqual(data['summary']['stays'], 0)


class FocusMapParentTests(TestCase):
    def test_subtask_with_parent_in_progress_goes_in_an_envelope(self):
        p, c = ft('G-P'), ft('G-C', parent='G-P')
        data = focus([p, c], {
            'G-P': [tr(at(1, '08:00'), 'Backlog', 'In Progress'), tr(at(1, '18:00'), 'In Progress', 'Done')],
            'G-C': [tr(at(1, '09:00'), 'Backlog', 'In Progress'), tr(at(1, '10:00'), 'In Progress', 'Done')],
        }, subs_total={'G-P': 3})
        runs = data['days'][0]['runs']
        self.assertEqual([r['family'] for r in runs], [None, 'G-P', None])
        self.assertEqual([c['key'] for c in runs[1]['cards']], ['G-C'])
        self.assertTrue(runs[1]['cards'][0]['parent_ip'])
        self.assertEqual((runs[1]['sub_active'], runs[1]['sub_total']), (1, 3))
        self.assertIsNone(data['alert'])

    def test_envelope_comes_back_marked_continued(self):
        p = ft('G-P')
        c1, c2 = ft('G-C1', parent='G-P'), ft('G-C2', parent='G-P')
        data = focus([p, c1, c2], {
            'G-P': [tr(at(1, '08:00'), 'Backlog', 'In Progress'), tr(at(1, '18:00'), 'In Progress', 'Done')],
            'G-C1': [tr(at(1, '09:00'), 'Backlog', 'In Progress'), tr(at(1, '10:00'), 'In Progress', 'Done')],
            'G-C2': [tr(at(1, '11:00'), 'Backlog', 'In Progress'), tr(at(1, '12:00'), 'In Progress', 'Done')],
        }, subs_total={'G-P': 3})
        envelopes = [r for r in data['days'][0]['runs'] if r['family']]
        self.assertEqual([r['continued'] for r in envelopes], [False, True])
        self.assertEqual([r['sub_active'] for r in envelopes], [2, 2])

    def test_subtask_while_parent_not_in_progress_warns(self):
        p, c = ft('G-P'), ft('G-C', parent='G-P')
        data = focus([p, c], {
            'G-P': [tr(at(1, '08:00'), 'Backlog', 'Bloqueado')],
            'G-C': [tr(at(1, '09:00'), 'Backlog', 'In Progress'), tr(at(1, '10:00'), 'In Progress', 'Done')],
        })
        card = data['days'][0]['cards'][0]
        self.assertTrue(card['parent_mine'])
        self.assertFalse(card['parent_ip'])
        self.assertEqual([r['family'] for r in data['days'][0]['runs']], [None])
        self.assertEqual(data['alert']['stays'], 1)
        self.assertEqual(data['alert']['items'], [{'id': 'G-C', 'parent': 'G-P', 'count': 1, 'secs': 3600}])
        # Time is unchanged: the subtask owns it as usual.
        self.assertEqual(card['secs'], 3600)

    def test_parent_that_is_not_the_viewers_gets_no_warning(self):
        c = ft('G-C', parent='X-9')
        data = focus([c], {'G-C': [tr(at(1, '09:00'), 'Backlog', 'In Progress'), tr(at(1, '10:00'), 'In Progress', 'Done')]},
                     parent_titles={'X-9': 'Outside parent'})
        card = data['days'][0]['cards'][0]
        self.assertEqual(card['parent'], {'id': 'X-9', 'title': 'Outside parent'})
        self.assertFalse(card['parent_mine'])
        self.assertIsNone(data['alert'])

    def test_fmt_secs(self):
        self.assertEqual([focus_map.fmt_secs(s) for s in (20, 60, 3661)], ['20 s', '1m', '1h 1m'])


class MapDateTests(TestCase):
    def test_parse_and_format(self):
        self.assertEqual(parse_map_date('23/Oct/2026'), dt.date(2026, 10, 23))
        self.assertEqual(parse_map_date('3/oct/2026'), dt.date(2026, 10, 3))
        self.assertEqual(parse_map_date('2026-10-23'), dt.date(2026, 10, 23))
        for bad in ('', '31/Feb/2026', '23/Xyz/2026', '23-10-2026'):
            self.assertIsNone(parse_map_date(bad))
        self.assertEqual(format_map_date(dt.date(2026, 10, 3)), '03/Oct/2026')


class FocusMapViewTests(MapPageMixin, TestCase):
    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_default_view_is_the_exclusive_chain(self):
        self.seed()
        response = self.page()
        self.assertEqual(response.context['view_mode'], 'exclusive')
        self.assertEqual([c['key'] for c in response.context['focus_days'][0]['cards']], ['GITIN-1', 'GITIN-2'])
        self.assertContains(response, 'Exclusive chain')
        self.assertNotContains(response, 'Copy as Mermaid')

    def test_alert_renders_for_a_subtask_under_a_parent_not_in_progress(self):
        self.ticket('GITIN-P', [(at(1, '08:00'), 'Backlog', 'Bloqueado')], 'Bloqueado')
        self.ticket('GITIN-C', [(at(1, '09:00'), 'Backlog', 'In Progress')], 'In Progress', parent='GITIN-P')
        response = self.page()
        self.assertContains(response, 'ran under a parent that was not In Progress')
        self.assertContains(response, 'parent not In Progress')

    def test_range_params(self):
        self.seed()
        response = self.page(range='today')
        self.assertEqual(response.context['range_param'], 'today')
        response = self.page(range='custom', date_from='01/Oct/2026', date_to='02/Oct/2026')
        self.assertEqual((response.context['date_from_text'], response.context['date_to_text']), ('01/Oct/2026', '02/Oct/2026'))
        self.assertEqual(response.context['range_error'], '')

    def test_invalid_range_shows_an_error_and_falls_back_to_week(self):
        for params in ({'date_from': 'nope', 'date_to': '01/Oct/2026'},
                       {'date_from': '05/Oct/2026', 'date_to': '01/Oct/2026'}):
            with self.subTest(params=params):
                response = self.page(**params)
                self.assertTrue(response.context['range_error'])
                self.assertEqual(response.context['range_param'], 'week')
                self.assertContains(response, 'dd/mmm/yyyy')

    def test_overlap_view_is_the_entries_map(self):
        self.seed()
        response = self.page(time='overlap')
        self.assertEqual(response.context['view_mode'], 'overlap')
        self.assertContains(response, 'Copy as Mermaid')

    def test_tag_filter_hides_other_tickets(self):
        self.seed()
        response = self.page(tags='INFRADEVOPS')
        self.assertEqual({c['key'] for d in response.context['focus_days'] for c in d['cards']}, {'GITIN-1'})

    def test_report_links_to_the_map_and_no_longer_renders_it(self):
        self.seed()
        with mock.patch('django.utils.timezone.now', return_value=at(2, '12:00')):
            response = self.client.get(reverse('timetracking-report'), {'range': 'week'})
        self.assertContains(response, reverse('timetracking-map'))
        self.assertNotContains(response, 'ip-map-card')
        self.assertNotIn('ip_map_days', response.context)
