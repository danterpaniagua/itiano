"""Tag time report (v5.21.0): `/time/report/`.

Pure functions (no DB access) on top of the Exclusive engine in `focus_map`: per ticket, the In
Progress time it owns, the Blocked time and the Overlapped time (In Progress while another ticket
owned the focus), all in working hours. Paused = Blocked + Overlapped. Also builds the AI prompt from
the `prompt_time_report` system prompt template.
"""
import datetime as dt
import re
from collections import defaultdict

from . import focus_map
from .map_views import MONTHS

UTC = dt.timezone.utc
DEFAULT_TAGS = 'SmartPedidos, SmartLoyalty, Operaciones, SmartCloud'
MIN_PERIOD_SECONDS = 60
SECTION_LIMIT = 1500
DESCRIPTION_LIMIT = 600
PROMPT_ID = 'prompt_time_report'

PROMPT_DEFAULT = """You are helping me summarise Jira work. Scope: tags {tag}, range {range}.

For every ticket below write:
1. A short description of what the ticket was about (one or two sentences).
2. A brief reason for each Blocked period and for each Overlapped period (the ticket was In Progress but another ticket had the focus). Together they are the ticket's "Paused" time.

Use the ticket's "Qué pasó" section as the main source. If it does not explain a period, write "reason unknown" and do not guess. Keep each ticket to a few lines. Answer in English.

Times are working hours (WH). IP = In Progress time the ticket owned. Paused = Blocked + Overlapped.

Every ticket has a "Transition map" in a text block, oldest first: `A -> B` is a status change (with the Blocked time when it leaves Blocked), and a line starting with `||` is an Overlapped handoff: the ticket stayed In Progress but another ticket took the focus (`resumed` when it got the focus back). Use the map to see when and in what order each pause happened.

{tickets}
"""


def parse_tags(text):
    """Unique, trimmed tag names from a comma / newline separated text, in order."""
    seen = []
    for part in re.split(r'[,\n]', text or ''):
        part = part.strip()
        if part and part not in seen:
            seen.append(part)
    return seen


def default_tags():
    from settings_hub.models import get_app_setting
    return parse_tags(get_app_setting('time_report_default_tags', DEFAULT_TAGS))


def _clip(a, b, lo, hi):
    a, b = max(a, lo), min(b, hi)
    return (a, b) if b > a else None


def _merge(periods):
    merged = []
    for period in periods:
        if merged and merged[-1]['end'] == period['start'] and merged[-1].get('owner') == period.get('owner'):
            merged[-1]['end'] = period['end']
        else:
            merged.append(dict(period))
    return merged


# ---------------------------------------------------------------------------
# Time rules
# ---------------------------------------------------------------------------

def ip_seconds(segs, slices, start, end, tz, schedule):
    """({ticket key: working seconds owned in IP}, {keys with any owned time in range}). Carry-over rule as the map."""
    segmap = {s['id']: s for s in segs}
    totals = defaultdict(int)
    touched = set()
    for seg_id, pieces in slices.items():
        seg = segmap[seg_id]
        for a, b in pieces:
            clipped = _clip(a, b, start, end)
            if not clipped:
                continue
            touched.add(seg['key'])
            for x, y in focus_map._split_days(*clipped, tz):
                day = x.astimezone(tz).date()
                day_start = dt.datetime.combine(day, dt.time(), tzinfo=tz)
                parts = focus_map.carry_trim(schedule, tz, seg['start'], (x, y)) if seg['start'] < day_start else [(x, y)]
                totals[seg['key']] += sum(focus_map.working_seconds(schedule, tz, p, q) for p, q in parts)
    return totals, touched


def blocked_periods(history, categories, start, end, now, schedule, tz):
    """Periods in a `blocked` category status inside [start, end]: [{start, end, status, wh_secs}]."""
    raw = []
    current = None
    for hop in sorted(history, key=lambda h: h['at']):
        if current:
            raw.append({'start': current[0], 'end': hop['at'], 'status': current[1]})
            current = None
        if focus_map._category(hop['to_status'], categories) == 'blocked':
            current = (hop['at'], hop['to_status'])
    if current:
        raw.append({'start': current[0], 'end': now, 'status': current[1]})
    out = []
    for period in _merge(raw):
        clipped = _clip(period['start'], period['end'], start, min(end, now))
        if clipped:
            out.append({
                'start': clipped[0], 'end': clipped[1], 'status': period['status'],
                'wh_secs': focus_map.working_seconds(schedule, tz, *clipped),
            })
    return out


def overlapped_periods(segs, slices, start, end, now, schedule, tz):
    """{ticket key: [{start, end, owner, wh_secs}]}: In Progress time the ticket did not own, with the
    key of the ticket that did."""
    segmap = {s['id']: s for s in segs}
    owners = sorted((a, b, segmap[seg_id]['key']) for seg_id, pieces in slices.items() for a, b in pieces)
    hi = min(end, now)
    out = defaultdict(list)
    for seg in segs:
        window = _clip(seg['start'], min(seg['end'] or now, now), start, hi)
        if not window:
            continue
        cursor = window[0]
        gaps = []
        for a, b in sorted(slices.get(seg['id'], [])):
            a, b = max(a, window[0]), min(b, window[1])
            if b <= a:
                continue
            if a > cursor:
                gaps.append((cursor, a))
            cursor = max(cursor, b)
        if cursor < window[1]:
            gaps.append((cursor, window[1]))
        for gap_a, gap_b in gaps:
            for owner_a, owner_b, owner in owners:
                if owner == seg['key']:
                    continue
                x, y = max(owner_a, gap_a), min(owner_b, gap_b)
                if y > x:
                    out[seg['key']].append({'start': x, 'end': y, 'owner': owner})
    result = {}
    for key, periods in out.items():
        merged = _merge(sorted(periods, key=lambda p: p['start']))
        for period in merged:
            period['wh_secs'] = focus_map.working_seconds(schedule, tz, period['start'], period['end'])
        result[key] = merged
    return result


def finished_at(history, categories):
    """When the ticket reached its current `done` status, or None when it is not done."""
    done = None
    for hop in sorted(history, key=lambda h: h['at']):
        done = hop['at'] if focus_map._category(hop['to_status'], categories) == 'done' else None
    return done


def build_rows(tickets, transitions, categories, schedule, tz, start, end, now, created=None):
    """{ticket key: row} for every ticket that had IP, Blocked or Overlapped time in the range, or was
    created / finished in it. Ownership is decided over all `tickets`, so tag filters never change it."""
    created = created or {}
    segs = focus_map.build_segments(tickets, transitions, categories)
    parent_of = {t.issue_key: t.parent_key for t in tickets}
    slices = focus_map.owned_slices(segs, parent_of, start, now)
    ip, ip_touched = ip_seconds(segs, slices, start, end, tz, schedule)
    overlapped = overlapped_periods(segs, slices, start, end, now, schedule, tz)
    titles = {t.issue_key: t.title for t in tickets}
    rows = {}
    for ticket in tickets:
        key = ticket.issue_key
        history = transitions.get(key, [])
        blocked = blocked_periods(history, categories, start, end, now, schedule, tz)
        over = overlapped.get(key, [])
        for period in over:
            period['owner_title'] = titles.get(period['owner'], '')
        created_at = created.get(key) or ticket.created_at
        done_at = finished_at(history, categories)
        in_range = lambda moment: bool(moment and start <= moment <= end)  # noqa: E731
        if not (key in ip_touched or blocked or over or in_range(created_at) or in_range(done_at)):
            continue
        blocked_wh = sum(p['wh_secs'] for p in blocked)
        overlap_wh = sum(p['wh_secs'] for p in over)
        ordered = sorted(history, key=lambda h: h['at'])
        before = [h for h in ordered if h['at'] < start]
        until = [h for h in ordered if h['at'] <= min(end, now)]
        rows[key] = {
            'hops': [h for h in ordered if start <= h['at'] <= min(end, now)],
            'status_start': before[-1]['to_status'] if before else '',
            'status_end': until[-1]['to_status'] if until else '',
            'key': key, 'title': ticket.title, 'labels': list(ticket.labels or []),
            'ip_wh': int(ip.get(key, 0)), 'blocked_wh': int(blocked_wh), 'overlap_wh': int(overlap_wh),
            'paused_wh': int(blocked_wh + overlap_wh),
            'blocked_periods': blocked, 'overlap_periods': over,
            'created': created_at.astimezone(tz).date() if created_at else None,
            'finished': done_at.astimezone(tz).date() if done_at else None,
        }
    return rows


def build_sections(rows, tags):
    """[{tag, rows, totals}] in `tags` order plus the grand totals counting each ticket once."""
    sections = []
    for tag in tags:
        members = sorted((r for r in rows.values() if tag in r['labels']), key=lambda r: (-r['ip_wh'], r['key']))
        sections.append({'tag': tag, 'rows': members, 'totals': _totals(members)})
    unique = {r['key']: r for s in sections for r in s['rows']}
    return sections, _totals(unique.values())


def _totals(rows):
    rows = list(rows)
    totals = {
        'tickets': len(rows),
        'ip_wh': sum(r['ip_wh'] for r in rows),
        'blocked_wh': sum(r['blocked_wh'] for r in rows),
        'overlap_wh': sum(r['overlap_wh'] for r in rows),
        'paused_wh': sum(r['paused_wh'] for r in rows),
    }
    for name in ('ip', 'blocked', 'overlap', 'paused'):
        totals[f'{name}_label'] = focus_map.fmt_secs(totals[f'{name}_wh'])
    return totals


def decorate(rows):
    """Adds the display labels used by the page."""
    for row in rows.values():
        row['ip_label'] = focus_map.fmt_secs(row['ip_wh'])
        row['blocked_label'] = focus_map.fmt_secs(row['blocked_wh'])
        row['overlap_label'] = focus_map.fmt_secs(row['overlap_wh'])
        row['paused_label'] = focus_map.fmt_secs(row['paused_wh'])
    return rows


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r'^\s*h[1-6]\.\s*(.*?)\s*$')
_QUE_PASO_RE = re.compile(r'qu[eé]\s+pas[oó]', re.I)


def extract_que_paso(description):
    """The `h2. Qué pasó` section of a Jira wiki-markup description (up to the next heading), or ''."""
    if not isinstance(description, str):
        return ''
    lines = description.splitlines()
    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match and _QUE_PASO_RE.search(match.group(1)):
            body = []
            for following in lines[index + 1:]:
                if _HEADING_RE.match(following):
                    break
                body.append(following)
            return '\n'.join(body).strip()
    return ''


def _trim(text, limit):
    text = (text or '').strip()
    return text if len(text) <= limit else text[:limit].rstrip() + ' …'


def ticket_context(description):
    """The text the prompt gives the AI for one ticket."""
    section = extract_que_paso(description)
    if section:
        return 'Qué pasó:\n' + _trim(section, SECTION_LIMIT)
    if isinstance(description, str) and description.strip():
        return 'Qué pasó: (no such section) Description:\n' + _trim(description, DESCRIPTION_LIMIT)
    return 'Qué pasó: (no description stored)'


def fmt_stamp(moment, tz):
    local = moment.astimezone(tz)
    return f'{local.day:02d}/{MONTHS[local.month - 1]} {local:%H:%M}'


def fmt_day(day):
    return f'{day.day:02d}/{MONTHS[day.month - 1]}/{day.year}' if day else '-'


def transition_map(row, tz):
    """ASCII map of the ticket's story inside the range: status changes, and the Overlapped
    handoffs (`||` lines: another ticket took the focus), with working-hour durations."""
    events = []
    blocked_by_end = {p['end']: p for p in row['blocked_periods']}
    for hop in row['hops']:
        text = f"{hop['from_status'] or '?'} -> {hop['to_status']}"
        period = blocked_by_end.get(hop['at'])
        if period and period['wh_secs']:
            text += f"   [Blocked {focus_map.fmt_secs(period['wh_secs'])} WH]"
        events.append((hop['at'], 1, text))
    previous = None
    for period in row['overlap_periods']:
        if period['wh_secs'] < MIN_PERIOD_SECONDS:
            continue
        who = f"{period['owner']} \"{period['owner_title']}\""
        length = f"[{focus_map.fmt_secs(period['wh_secs'])} WH]"
        if previous and previous['end'] == period['start']:
            events.append((period['start'], 0, f"  || focus passed to {who}   {length}"))
        else:
            if previous:
                events.append((previous['end'], 0, '  || resumed'))
            events.append((period['start'], 0, f"  || paused: {who} took the focus   {length}"))
        previous = period
    if previous:
        events.append((previous['end'], 0, '  || resumed'))
    lines = []
    if row['status_start']:
        lines.append(f"(range start)  {row['status_start']}")
    lines += [f"{fmt_stamp(when, tz)}  {text}" for when, _, text in sorted(events, key=lambda e: (e[0], e[1]))]
    if row['status_end']:
        lines.append(f"(range end)    {row['status_end']}")
    return '\n'.join(lines) if lines else '(no status changes in this range)'


def ticket_block(row, description, tz):
    return '\n'.join([
        f"### {row['key']} · {row['title']}",
        f"Tags: {', '.join(row['labels']) or '-'} | Created: {fmt_day(row['created'])} | Finished: {fmt_day(row['finished'])}",
        (f"Time (WH): IP {row['ip_label']} · Blocked {row['blocked_label']} · Paused {row['paused_label']} "
         f"(Blocked {row['blocked_label']} + Overlapped {focus_map.fmt_secs(row['overlap_wh'])})"),
        'Transition map:',
        '```text',
        transition_map(row, tz),
        '```',
        ticket_context(description),
    ])


def build_prompt(template, tags, range_text, sections, descriptions, tz):
    """Fills `{tag}`, `{range}` and `{tickets}` (plain replacement, never str.format, so braces in the
    template are safe). Each ticket appears once, under the first of the selected tags it carries. When the
    template has no `{tickets}` the block is appended."""
    blocks = []
    listed = set()
    for section in sections:
        members = [r for r in section['rows'] if r['key'] not in listed]
        if not members:
            continue
        blocks.append(f"## Tag: {section['tag']}")
        for row in members:
            listed.add(row['key'])
            blocks.append(ticket_block(row, descriptions.get(row['key'], ''), tz))
    tickets = '\n\n'.join(blocks) if blocks else '(no tickets with activity in this range)'
    text = template.replace('{tag}', ', '.join(tags)).replace('{range}', range_text)
    if '{tickets}' in text:
        return text.replace('{tickets}', tickets)
    return text.rstrip() + '\n\n' + tickets + '\n'
