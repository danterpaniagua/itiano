"""In Progress map: per-day chains of In Progress entries (v5.18.0).

Pure functions — no DB access. The view hands in the per-ticket status transitions it has
already fetched; this module decides what counts as an entry, where it came from and where it
went, so the rules are unit-testable without the report view.
"""
import datetime
import re

COLLAPSE_SECONDS = 60

ORIGIN_META = {
    'created': ('bi-plus-circle-fill', 'ipm-created', 'Created (first time in progress)', '✚'),
    'blocked': ('bi-slash-circle-fill', 'ipm-blocked', 'Resumed from blocked', '⛔'),
    'testing': ('bi-flask', 'ipm-testing', 'Resumed from testing', '◇'),
    'queue': ('bi-circle', 'ipm-queue', 'Taken from the queue', '○'),
    'done': ('bi-arrow-counterclockwise', 'ipm-done', 'Reopened from done', '✔'),
}
DEST_META = {
    'done': ('bi-check-circle-fill', 'ipm-done', 'Moved to', '✔'),
    'blocked': ('bi-slash-circle-fill', 'ipm-blocked', 'Moved to', '⛔'),
    'testing': ('bi-flask', 'ipm-testing', 'Moved to', '◇'),
    'queue': ('bi-circle', 'ipm-queue', 'Moved to', '○'),
    'ip': ('bi-play-circle-fill', 'ipm-ip', 'Still in progress', '▶'),
}
DEST_ORDER = ['done', 'blocked', 'testing', 'queue', 'ip']
ORIGIN_ORDER = ['created', 'blocked', 'testing', 'queue', 'done']


def _fmt(seconds):
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f'{days}d {hours}h'
    if hours:
        return f'{hours}h {minutes}m'
    return f'{minutes}m'


def _category(status, categories):
    return categories.get((status or '').lower(), 'other')


def _origin_kind(from_category):
    if from_category in ('blocked', 'testing', 'done'):
        return from_category
    return 'queue'


def _dest_kind(category):
    if category in ('done', 'blocked', 'testing'):
        return category
    return 'queue'


def collect_entries(tickets, transitions, categories, end_dt):
    """Every In Progress entry of every ticket, over the full history, oldest first.

    An entry is a transition into an in_progress-category status from a status that is not in
    that category (so `In Progress -> En curso` is the same stay, not a new entry).
    """
    entries = []
    for ticket in tickets:
        history = sorted(transitions.get(ticket.issue_key, []), key=lambda t: t['at'])
        seen_entry = False
        for idx, current in enumerate(history):
            if _category(current['to_status'], categories) != 'in_progress':
                continue
            previous_status = history[idx - 1]['to_status'] if idx > 0 else current['from_status']
            previous_category = _category(previous_status, categories)
            if previous_category == 'in_progress':
                continue

            destination = next(
                (t for t in history[idx + 1:] if _category(t['to_status'], categories) != 'in_progress'),
                None,
            )
            if destination is None:
                dest_kind, dest_status, left_at = 'ip', '', end_dt
            else:
                dest_kind = _dest_kind(_category(destination['to_status'], categories))
                dest_status, left_at = destination['to_status'], destination['at']

            entries.append({
                'ticket': ticket,
                'at': current['at'],
                'origin': 'created' if not seen_entry else _origin_kind(previous_category),
                'origin_status': previous_status,
                'dest': dest_kind,
                'dest_status': dest_status,
                'left_at': left_at,
                'ip_secs': max(0, int((left_at - current['at']).total_seconds())),
            })
            seen_entry = True
    entries.sort(key=lambda e: (e['at'], e['ticket'].issue_key))
    return entries


def drop_parent_entries(entries, collapse_seconds=COLLAPSE_SECONDS):
    """Drop a parent's entry when one of its children entered IP within `collapse_seconds`
    of it (either order): moving a child to IP commonly auto-transitions the parent too."""
    child_times = {}
    for entry in entries:
        parent_key = entry['ticket'].parent_key
        if parent_key:
            child_times.setdefault(parent_key, []).append(entry['at'])
    kept = []
    for entry in entries:
        times = child_times.get(entry['ticket'].issue_key, ())
        if any(abs((child_at - entry['at']).total_seconds()) <= collapse_seconds for child_at in times):
            continue
        kept.append(entry)
    return kept


def _card(entry, working_seconds=None):
    ticket = entry['ticket']
    origin_icon, origin_color, origin_tip, _ = ORIGIN_META[entry['origin']]
    dest_icon, dest_color, dest_tip, _ = DEST_META[entry['dest']]
    if entry['dest'] == 'ip':
        dest_title = f'{dest_tip} ({_fmt(entry["ip_secs"])} so far)'
    else:
        dest_title = f'{dest_tip} {entry["dest_status"]} after {_fmt(entry["ip_secs"])} in progress'
    origin_title = origin_tip
    if entry['origin'] != 'created' and entry['origin_status']:
        origin_title = f'{origin_tip} ({entry["origin_status"]})'
    return {
        'key': ticket.issue_key,
        'title': ticket.title,
        'labels': list(ticket.labels or []),
        'origin': entry['origin'],
        'origin_icon': origin_icon,
        'origin_color': origin_color,
        'origin_title': origin_title,
        'dest': entry['dest'],
        'dest_icon': dest_icon,
        'dest_color': dest_color,
        'dest_title': dest_title,
        'total_secs': entry['ip_secs'],
        'wh_secs': working_seconds(entry['at'], entry['left_at']) if working_seconds else None,
        'repeat': 1,
    }


def build_days(entries, tz, working_seconds=None):
    """Group entries by day (in `tz`), newest day first, into ordered cards (each day's chain stays
    oldest to newest, left to right). Consecutive entries of the same
    ticket in a day become one card with a repeat count; origin of the first and destination
    of the last entry are kept; the time in progress of merged stays is summed.

    `working_seconds(start, end)` (optional) clips a stay to the working schedule; without it the
    cards carry no working-hours time."""
    days = []
    by_date = {}
    for entry in entries:
        local_date = entry['at'].astimezone(tz).date()
        day = by_date.get(local_date)
        if day is None:
            day = {
                'date': local_date,
                'label': datetime.datetime.combine(local_date, datetime.time()).strftime('%a %d/%m'),
                'cards': [],
                'count': 0,
            }
            by_date[local_date] = day
            days.append(day)
        day['count'] += 1
        card = _card(entry, working_seconds)
        last = day['cards'][-1] if day['cards'] else None
        if last and last['key'] == card['key']:
            last['repeat'] += 1
            last['total_secs'] += card['total_secs']
            if card['wh_secs'] is not None:
                last['wh_secs'] += card['wh_secs']
            for field in ('dest', 'dest_icon', 'dest_color', 'dest_title'):
                last[field] = card[field]
        else:
            day['cards'].append(card)
    for day in days:
        for card in day['cards']:
            card['total_label'] = _fmt(card['total_secs'])
            card['wh_label'] = _fmt(card['wh_secs']) if card['wh_secs'] is not None else '—'
    days.sort(key=lambda d: d['date'], reverse=True)
    return days


def mermaid_text(days):
    """Copy-only `flowchart LR` text, one block per day. Keys are sanitised: they come from
    Jira but end up inside a quoted Mermaid label."""
    blocks = []
    for day in days:
        lines = [f'%% {day["label"]}', 'flowchart LR']
        for idx, card in enumerate(day['cards']):
            key = re.sub(r'[^A-Za-z0-9_-]', '', card['key'])
            origin = ORIGIN_META[card['origin']][3]
            dest = DEST_META[card['dest']][3]
            repeat = f' x{card["repeat"]}' if card['repeat'] > 1 else ''
            lines.append(f'  n{idx}["{key} {origin}→{dest}{repeat}"]')
        if len(day['cards']) > 1:
            lines.append('  ' + ' --> '.join(f'n{i}' for i in range(len(day['cards']))))
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)


def summarize(entries):
    dest_counts = {kind: 0 for kind in DEST_ORDER}
    origin_counts = {kind: 0 for kind in ORIGIN_ORDER}
    for entry in entries:
        dest_counts[entry['dest']] += 1
        origin_counts[entry['origin']] += 1
    return {
        'entries': len(entries),
        'tickets': len({entry['ticket'].issue_key for entry in entries}),
        'destinations': [
            {'kind': kind, 'symbol': DEST_META[kind][3], 'count': dest_counts[kind],
             'icon': DEST_META[kind][0], 'color': DEST_META[kind][1]}
            for kind in DEST_ORDER if dest_counts[kind]
        ],
        'origins': [
            {'kind': kind, 'symbol': ORIGIN_META[kind][3], 'count': origin_counts[kind]}
            for kind in ORIGIN_ORDER if origin_counts[kind]
        ],
    }


def build_ip_map(tickets, transitions, categories, start_dt, end_dt, tz, visible_keys=None,
                 working_seconds=None):
    """Build the map for [start_dt, end_dt].

    `tickets`/`transitions` cover everything the viewer owns, so first-ever detection and the
    parent collapse see the full picture; `visible_keys` (optional set) then restricts what is
    shown (the report's tag filter). `working_seconds` (optional) is the schedule clipper used for
    the W-H card time; pass None when the viewer has no WorkSchedule.
    """
    entries = collect_entries(tickets, transitions, categories, end_dt)
    entries = drop_parent_entries(entries)
    entries = [e for e in entries if start_dt <= e['at'] <= end_dt]
    if visible_keys is not None:
        entries = [e for e in entries if e['ticket'].issue_key in visible_keys]
    days = build_days(entries, tz, working_seconds)
    return {
        'days': days,
        'has_wh': working_seconds is not None,
        'summary': summarize(entries),
        'mermaid': mermaid_text(days),
    }
