"""In Progress map, focus (Exclusive) view (v5.18.4).

Pure functions, no DB access: the view hands in the viewer's tickets, their status transitions,
the status categories and the WorkSchedule. Builds the time-ordered chain of stays under the
Exclusive rule (only one ticket owns In Progress time at any instant: the latest entry wins, a
parent yields to its active child, the previous ticket resumes when the owner leaves), the parent
envelopes and the "parent not In Progress" alert.

The ownership sweep and the carry-over rule mirror `DailyReportView` (v5.16.0 / v5.18.3); a parity
test keeps the two in step until the shared time-rules refactor.
"""
import datetime as dt
from collections import defaultdict

from . import ip_map

FOLD_SECONDS = 60
UTC = dt.timezone.utc
_WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


def fmt_secs(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f'{seconds} s'
    hours, minutes = divmod(seconds // 60, 60)
    return f'{hours}h {minutes}m' if hours else f'{minutes}m'


def _category(status, categories):
    return categories.get((status or '').lower(), 'other')


# ---------------------------------------------------------------------------
# Working schedule helpers
# ---------------------------------------------------------------------------

def _is_working_day(schedule, day):
    return bool(getattr(schedule, _WEEKDAYS[day.weekday()], False))


def working_seconds(schedule, tz, start, end):
    """Seconds of [start, end] that fall inside the schedule (working days and hours)."""
    if not schedule or not schedule.start_time or not schedule.end_time:
        return 0
    total = 0
    day = start.astimezone(tz).date()
    end_day = end.astimezone(tz).date()
    while day <= end_day:
        if _is_working_day(schedule, day):
            work_start = dt.datetime.combine(day, schedule.start_time, tzinfo=tz)
            work_end = dt.datetime.combine(day, schedule.end_time, tzinfo=tz)
            lo, hi = max(start, work_start), min(end, work_end)
            if hi > lo:
                total += (hi - lo).total_seconds()
        day += dt.timedelta(days=1)
    return int(total)


def carry_trim(schedule, tz, entered_at, interval):
    """[lo, hi] minus the overnight zones of a stay carried over from a previous day: from each
    local day's 00:00 to the first working hour (the whole day when it is not a working day).
    Returns a list of (lo, hi) pieces. Same rule as the report's `_carry_trim`."""
    lo, hi = interval
    if not schedule or not schedule.start_time or not schedule.end_time:
        return [(lo, hi)]
    pieces = [(lo, hi)]
    day = lo.astimezone(tz).date()
    end_day = hi.astimezone(tz).date()
    while day <= end_day:
        day_start = dt.datetime.combine(day, dt.time(), tzinfo=tz)
        if entered_at < day_start:
            if _is_working_day(schedule, day):
                zone = (day_start, dt.datetime.combine(day, schedule.start_time, tzinfo=tz))
            else:
                zone = (day_start, day_start + dt.timedelta(days=1))
            kept = []
            for a, b in pieces:
                if zone[1] <= a or zone[0] >= b:
                    kept.append((a, b))
                    continue
                if zone[0] > a:
                    kept.append((a, zone[0]))
                if zone[1] < b:
                    kept.append((zone[1], b))
            pieces = kept
        day += dt.timedelta(days=1)
    return pieces


# ---------------------------------------------------------------------------
# Stays and ownership
# ---------------------------------------------------------------------------

def build_segments(tickets, transitions, categories):
    """In Progress stays (by status category: `In Progress -> En curso` is one stay)."""
    segs = []
    for ticket in tickets:
        history = sorted(transitions.get(ticket.issue_key, []), key=lambda h: h['at'])
        first_ever = True
        current = None
        for idx, hop in enumerate(history):
            previous_status = history[idx - 1]['to_status'] if idx else hop['from_status']
            is_ip = _category(hop['to_status'], categories) == 'in_progress'
            was_ip = _category(previous_status, categories) == 'in_progress'
            if is_ip and not was_ip:
                current = {
                    'key': ticket.issue_key, 'start': hop['at'], 'end': None,
                    'origin': 'created' if first_ever else ip_map._origin_kind(_category(previous_status, categories)),
                    'dest': None,
                }
                first_ever = False
                segs.append(current)
            elif was_ip and not is_ip and current is not None:
                current['end'] = hop['at']
                current['dest'] = ip_map._dest_kind(_category(hop['to_status'], categories))
                current = None
    for number, seg in enumerate(segs):
        seg['id'] = number
    return segs


def owned_slices(segs, parent_of, start_dt, now):
    """{segment id: [(a, b), ...]}: the time each stay owns under the Exclusive rule."""
    sweep_from = min([start_dt] + [s['start'] for s in segs if s['end'] is None])
    ip_segs = []
    for seg in segs:
        seg_end = min(seg['end'] or now, now)
        if seg_end <= sweep_from or seg_end <= seg['start']:
            continue
        ip_segs.append((seg['start'], seg_end, seg['key'], seg['id']))
    ip_segs.sort()
    points = sorted({p for a, b, _, _ in ip_segs for p in (a, b)})
    slices = defaultdict(list)
    active = []
    next_seg = 0
    for a, b in zip(points, points[1:]):
        while next_seg < len(ip_segs) and ip_segs[next_seg][0] <= a:
            active.append(ip_segs[next_seg])
            next_seg += 1
        active = [x for x in active if x[1] > a]
        if not active:
            continue
        active_keys = {x[2] for x in active}
        candidates = [
            x for x in active
            if not any(parent_of.get(k) == x[2] for k in active_keys if k != x[2])
        ] or active
        owner = max(candidates, key=lambda x: (x[0], x[2]))
        owned = slices[owner[3]]
        if owned and owned[-1][1] == a:
            owned[-1] = (owned[-1][0], b)
        else:
            owned.append((a, b))
    return slices


def _split_days(a, b, tz):
    pieces = []
    while True:
        day_start = a.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        next_midnight = (day_start + dt.timedelta(days=1)).astimezone(UTC)
        if b <= next_midnight:
            pieces.append((a, b))
            return pieces
        pieces.append((a, next_midnight))
        a = next_midnight


# ---------------------------------------------------------------------------
# Cards, envelopes, alert
# ---------------------------------------------------------------------------

def _hhmm(value, tz):
    return value.astimezone(tz).strftime('%H:%M')


def _make_card(ticket, seg, start, end, secs, wh_secs):
    origin_icon, origin_color, origin_tip, _ = ip_map.ORIGIN_META[seg['origin']]
    return {
        'key': ticket.issue_key, 'title': ticket.title, 'labels': list(ticket.labels or []),
        'origin': seg['origin'], 'origin_icon': origin_icon, 'origin_color': origin_color, 'origin_title': origin_tip,
        '_seg': seg, '_start': start, '_end': end, 'secs': secs, 'wh_secs': wh_secs, 'folds': [],
    }


def _finish_card(card, tz, now_edge, schedule):
    seg = card['_seg']
    ended_here = seg['end'] is not None and abs((card['_end'] - seg['end']).total_seconds()) < 1
    if ended_here:
        dest, paused, running = seg['dest'], False, False
    elif seg['end'] is None and card['_end'] >= now_edge - dt.timedelta(seconds=1):
        dest, paused, running = 'ip', False, True
    else:
        dest, paused, running = 'ip', True, False
    dest_icon, dest_color, dest_tip, _ = ip_map.DEST_META[dest]
    card.update({
        'dest': dest, 'dest_icon': dest_icon, 'dest_color': dest_color, 'dest_title': dest_tip,
        'paused': paused, 'running': running,
        'start': _hhmm(card['_start'], tz), 'end': _hhmm(card['_end'], tz),
        'total_label': fmt_secs(card['secs']), 'wh_label': fmt_secs(card['wh_secs']),
        'folded': (
            f"{len(card['folds'])} short return{'s' if len(card['folds']) > 1 else ''} "
            f"({', '.join(f'{f} s' for f in card['folds'])}) folded"
        ) if card['folds'] else '',
    })


def _group_runs(cards, subs_total):
    """Envelope runs: consecutive subtask stays whose parent is also In Progress share one envelope
    (marked continued when the family comes back later); every other stay is a plain card."""
    runs = []
    seen = set()
    for card in cards:
        parent = card['parent']
        family = parent['id'] if parent and card['parent_ip'] else None
        last = runs[-1] if runs else None
        if family and last and last['family'] == family:
            last['cards'].append(card)
        else:
            runs.append({'family': family, 'cards': [card], 'continued': bool(family and family in seen)})
        if family:
            seen.add(family)
    for run in runs:
        run['secs'] = sum(c['secs'] for c in run['cards'])
        run['wh_secs'] = sum(c['wh_secs'] for c in run['cards'])
        run['total_label'] = fmt_secs(run['secs'])
        run['wh_label'] = fmt_secs(run['wh_secs'])
        if run['family']:
            first = run['cards'][0]['parent']
            run['title'] = first['title']
            active = len({c['key'] for c in cards if c['parent'] and c['parent']['id'] == run['family']})
            run['sub_active'] = active
            run['sub_total'] = max(subs_total.get(run['family'], active), active)
    return runs


def _alert(days):
    grouped = {}
    for day in days:
        for card in day['cards']:
            parent = card['parent']
            if parent and card['parent_mine'] and not card['parent_ip']:
                item = grouped.setdefault((card['key'], parent['id']), {'id': card['key'], 'parent': parent['id'], 'count': 0, 'secs': 0})
                item['count'] += 1
                item['secs'] += card['secs']
    if not grouped:
        return None
    items = sorted(grouped.values(), key=lambda i: (-i['count'], i['id']))
    secs = sum(i['secs'] for i in items)
    return {'stays': sum(i['count'] for i in items), 'secs': secs, 'total_label': fmt_secs(secs), 'items': items}


def build_focus_map(tickets, transitions, categories, schedule, tz, start_dt, end_dt, now,
                    visible_keys=None, parent_titles=None, subs_total=None):
    """The Exclusive chain for [start_dt, end_dt].

    `visible_keys` (optional set) hides the other tickets' cards after ownership is decided, so the
    owned time never depends on the tag filter. `parent_titles` ({key: title}) names parents that
    are not among `tickets`; `subs_total` ({parent key: number of subtasks}) feeds "1 of 2 subtasks".
    """
    parent_titles = parent_titles or {}
    subs_total = subs_total or {}
    by_key = {t.issue_key: t for t in tickets}
    parent_of = {t.issue_key: t.parent_key for t in tickets}
    segs = build_segments(tickets, transitions, categories)
    slices = owned_slices(segs, parent_of, start_dt, now)
    now_edge = min(now, end_dt)

    per_day = defaultdict(list)
    for seg_id, pieces in slices.items():
        for a, b in pieces:
            a, b = max(a, start_dt), min(b, end_dt)
            if b <= a:
                continue
            for x, y in _split_days(a, b, tz):
                per_day[x.astimezone(tz).date()].append((x, y, seg_id))
    segmap = {s['id']: s for s in segs}

    days = []
    for day in sorted(per_day, reverse=True):
        day_start = dt.datetime.combine(day, dt.time(), tzinfo=tz).astimezone(UTC)
        cards = []
        for x, y, seg_id in sorted(per_day[day]):
            seg = segmap[seg_id]
            carried = seg['start'] < day_start
            if carried:
                pieces = carry_trim(schedule, tz, seg['start'], (x, y))
                if not pieces:
                    continue
                x, y = pieces[0][0], pieces[-1][1]
                secs = int(sum((b - a).total_seconds() for a, b in pieces))
            else:
                secs = int((y - x).total_seconds())
            wh = working_seconds(schedule, tz, x, y)
            resumed = x > seg['start'] + dt.timedelta(seconds=1) and x > day_start
            previous = next((c for c in reversed(cards) if c['key'] == seg['key']), None)
            if resumed and secs < FOLD_SECONDS and previous:
                previous['secs'] += secs
                previous['wh_secs'] += wh
                previous['folds'].append(secs)
                previous['_end'] = y if previous['_seg'] is seg else previous['_end']
                previous['_seg'] = seg
                continue
            if cards and cards[-1]['key'] == seg['key'] and cards[-1]['_seg'] is seg:
                last = cards[-1]
                last['secs'] += secs
                last['wh_secs'] += wh
                last['_end'] = y
                continue
            card = _make_card(by_key[seg['key']], seg, x, y, secs, wh)
            first_of_ticket = previous is None
            card['since'] = seg['start'].astimezone(tz).strftime('%a %d/%m %H:%M') if (carried and first_of_ticket) else ''
            card['resumed'] = bool(resumed and not (carried and first_of_ticket))
            cards.append(card)

        for card in cards:
            _finish_card(card, tz, now_edge, schedule)
            ticket = by_key[card['key']]
            parent_key = ticket.parent_key
            parent_ticket = by_key.get(parent_key) if parent_key else None
            if parent_key:
                title = parent_ticket.title if parent_ticket else parent_titles.get(parent_key, parent_key)
                card['parent'] = {'id': parent_key, 'title': title}
                card['parent_mine'] = parent_ticket is not None
                card['parent_ip'] = any(
                    s['key'] == parent_key and s['start'] <= card['_start'] < (s['end'] or now)
                    for s in segs
                )
            else:
                card['parent'], card['parent_mine'], card['parent_ip'] = None, False, False

        if visible_keys is not None:
            cards = [c for c in cards if c['key'] in visible_keys]
        if not cards:
            continue
        for number, card in enumerate(cards, 1):
            card['n'] = number
        runs = _group_runs(cards, subs_total)
        days.append({
            'date': day,
            'label': dt.datetime.combine(day, dt.time()).strftime('%a %d/%m'),
            'cards': cards, 'runs': runs,
            'count': len(cards), 'tickets': len({c['key'] for c in cards}),
        })

    return {
        'days': days,
        'alert': _alert(days),
        'summary': {
            'stays': sum(d['count'] for d in days),
            'tickets': len({c['key'] for d in days for c in d['cards']}),
        },
    }
