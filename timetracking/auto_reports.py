"""Automatic personal Time Report notes (v5.22.0): settings and period maths (pure, no DB except settings).

A period is *closed* once its last day has passed in the user's timezone. Ids:
month `YYYY-MM`, week `YYYY-MM_Wnn` (ISO week number; the month is the one of the week's Monday),
other `YYYY-MM-DD_<N>D` (start date of an N-day block counted from an anchor date).
"""
import datetime as dt

from . import map_views

KEYS = {
    'weekly': 'time_report_auto_weekly',
    'monthly': 'time_report_auto_monthly',
    'other': 'time_report_auto_other',
    'other_days': 'time_report_auto_other_days',
    'other_anchor': 'time_report_auto_other_anchor',
}
LAST_RUN_KEY = 'time_report_auto_last_run'
DEFAULT_OTHER_DAYS = 14
MIN_OTHER_DAYS = 2
MAX_OTHER_DAYS = 366
NOTEBOOK_ROOT = 'Personal'
NOTEBOOK_REPORTS = 'Jira Time Report'


def load_settings():
    """{'weekly', 'monthly', 'other': bool, 'other_days': int, 'other_anchor': date | None}."""
    from settings_hub.models import get_app_setting

    def flag(name, default):
        return get_app_setting(KEYS[name], default) == '1'

    try:
        days = int(get_app_setting(KEYS['other_days'], str(DEFAULT_OTHER_DAYS)))
    except ValueError:
        days = DEFAULT_OTHER_DAYS
    anchor_text = get_app_setting(KEYS['other_anchor'], '')
    try:
        anchor = dt.date.fromisoformat(anchor_text) if anchor_text else None
    except ValueError:
        anchor = None
    return {
        'weekly': flag('weekly', '1'), 'monthly': flag('monthly', '1'), 'other': flag('other', '0'),
        'other_days': min(max(days, MIN_OTHER_DAYS), MAX_OTHER_DAYS), 'other_anchor': anchor,
    }


def closed_months(today, count=1):
    periods = []
    end = today.replace(day=1) - dt.timedelta(days=1)
    for _ in range(count):
        start = end.replace(day=1)
        periods.append({'kind': 'monthly', 'id': f'{start:%Y-%m}', 'start': start, 'end': end})
        end = start - dt.timedelta(days=1)
    return periods


def closed_weeks(today, count=1):
    periods = []
    end = today - dt.timedelta(days=today.weekday() + 1)   # last Sunday
    for _ in range(count):
        start = end - dt.timedelta(days=6)
        periods.append({
            'kind': 'weekly', 'id': f'{start:%Y-%m}_W{start.isocalendar()[1]:02d}', 'start': start, 'end': end,
        })
        end = start - dt.timedelta(days=1)
    return periods


def closed_blocks(today, anchor, days, count=1):
    """The latest `count` closed N-day blocks counted from `anchor` (none before the first block closes)."""
    if anchor is None:
        return []
    closed = (today - anchor).days // days
    periods = []
    for k in range(closed - 1, max(closed - 1 - count, -1), -1):
        start = anchor + dt.timedelta(days=k * days)
        periods.append({
            'kind': 'other', 'id': f'{start.isoformat()}_{days}D', 'start': start,
            'end': start + dt.timedelta(days=days - 1),
        })
    return periods


def periods_for(settings, today, backfill=1):
    """Closed periods to create for a user whose local date is `today`, newest first per kind."""
    periods = []
    if settings['weekly']:
        periods += closed_weeks(today, backfill)
    if settings['monthly']:
        periods += closed_months(today, backfill)
    if settings['other']:
        periods += closed_blocks(today, settings['other_anchor'], settings['other_days'], backfill)
    return periods


def title_for(period):
    return f"Jira Time Report {period['id']}"


def parse_anchor(text):
    """`dd/mmm/yyyy` or ISO date typed in settings, or None."""
    return map_views.parse_map_date(text)


def ensure_folder(user, day):
    """Personal / Jira Time Report / YYYY / MM for `day`, created on demand (an existing top-level
    notebook of the same name is reused)."""
    from notes.models import Notebook
    parent = None
    for name in (NOTEBOOK_ROOT, NOTEBOOK_REPORTS, f'{day.year}', f'{day.month:02d}'):
        parent, _ = Notebook.objects.get_or_create(owner=user, name=name, parent=parent, is_system=False)
    return parent
