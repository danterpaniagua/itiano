import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from jira_integration.models import JiraEvent, JiraTicket

from .models import TimeEntry, WorkSchedule


class TimeEntryListView(LoginRequiredMixin, View):
    def get(self, request):
        entries = TimeEntry.objects.filter(user=request.user).select_related('jira_ticket')
        ticket_filter = request.GET.get('ticket', '').strip()
        if ticket_filter:
            entries = entries.filter(jira_ticket__issue_key__icontains=ticket_filter)

        schedule = WorkSchedule.objects.filter(user=request.user).first()
        jira_username = schedule.jira_username.strip() if schedule and schedule.jira_username else ''
        active_tickets = []
        if jira_username:
            active_tickets = list(
                JiraTicket.objects.filter(
                    status__iexact='In Progress',
                    assignee__iexact=jira_username,
                    is_deleted=False,
                ).order_by('issue_key')
            )

        return render(request, 'timetracking/entry_list.html', {
            'entries': entries,
            'ticket_filter': ticket_filter,
            'active_tickets': active_tickets,
            'jira_username': jira_username,
        })


class TimeEntryCreateView(LoginRequiredMixin, View):
    def _get_ticket(self, issue_key):
        if issue_key:
            return JiraTicket.objects.filter(issue_key=issue_key).first()
        return None

    def get(self, request):
        ticket = self._get_ticket(request.GET.get('ticket', ''))
        tickets = JiraTicket.objects.order_by('issue_key')
        return render(request, 'timetracking/entry_form.html', {
            'tickets': tickets,
            'preselected_ticket': ticket,
            'today': datetime.date.today().isoformat(),
            'entry': None,
        })

    def post(self, request):
        issue_key = request.POST.get('jira_ticket', '').strip()
        date_str = request.POST.get('date', '').strip()
        minutes_str = request.POST.get('minutes', '').strip()
        activity = request.POST.get('activity', '').strip()

        errors = []
        ticket = JiraTicket.objects.filter(issue_key=issue_key).first()
        if not ticket:
            errors.append('Selecciona un ticket Jira válido.')
        try:
            date = datetime.date.fromisoformat(date_str)
        except ValueError:
            errors.append('Fecha inválida.')
            date = None
        try:
            minutes = int(minutes_str)
            if minutes <= 0:
                raise ValueError
        except ValueError:
            errors.append('Los minutos deben ser un número positivo.')
            minutes = None
        if not activity:
            errors.append('La actividad es obligatoria.')

        if errors:
            for e in errors:
                messages.error(request, e)
            tickets = JiraTicket.objects.order_by('issue_key')
            return render(request, 'timetracking/entry_form.html', {
                'tickets': tickets,
                'preselected_ticket': ticket,
                'today': date_str or datetime.date.today().isoformat(),
                'post': request.POST,
                'entry': None,
            })

        TimeEntry.objects.create(
            user=request.user,
            jira_ticket=ticket,
            date=date,
            minutes=minutes,
            activity=activity,
        )
        messages.success(request, 'Entrada de tiempo registrada.')
        next_url = request.POST.get('next') or 'timetracking-list'
        if next_url.startswith('/'):
            return redirect(next_url)
        return redirect(next_url)


class TimeEntryEditView(LoginRequiredMixin, View):
    def _get_entry(self, request, pk):
        entry = get_object_or_404(TimeEntry, pk=pk)
        if entry.user != request.user:
            raise PermissionDenied
        return entry

    def get(self, request, pk):
        entry = self._get_entry(request, pk)
        tickets = JiraTicket.objects.order_by('issue_key')
        return render(request, 'timetracking/entry_form.html', {
            'entry': entry,
            'tickets': tickets,
            'preselected_ticket': entry.jira_ticket,
            'today': entry.date.isoformat(),
        })

    def post(self, request, pk):
        entry = self._get_entry(request, pk)
        issue_key = request.POST.get('jira_ticket', '').strip()
        date_str = request.POST.get('date', '').strip()
        minutes_str = request.POST.get('minutes', '').strip()
        activity = request.POST.get('activity', '').strip()

        errors = []
        ticket = JiraTicket.objects.filter(issue_key=issue_key).first()
        if not ticket:
            errors.append('Selecciona un ticket Jira válido.')
        try:
            date = datetime.date.fromisoformat(date_str)
        except ValueError:
            errors.append('Fecha inválida.')
            date = None
        try:
            minutes = int(minutes_str)
            if minutes <= 0:
                raise ValueError
        except ValueError:
            errors.append('Los minutos deben ser un número positivo.')
            minutes = None
        if not activity:
            errors.append('La actividad es obligatoria.')

        if errors:
            for e in errors:
                messages.error(request, e)
            tickets = JiraTicket.objects.order_by('issue_key')
            return render(request, 'timetracking/entry_form.html', {
                'entry': entry,
                'tickets': tickets,
                'preselected_ticket': ticket or entry.jira_ticket,
                'today': date_str,
                'post': request.POST,
            })

        entry.jira_ticket = ticket
        entry.date = date
        entry.minutes = minutes
        entry.activity = activity
        entry.save()
        messages.success(request, 'Entrada actualizada.')
        return redirect('timetracking-list')


class TimeEntryDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        entry = get_object_or_404(TimeEntry, pk=pk, user=request.user)
        entry.delete()
        messages.success(request, 'Entrada eliminada.')
        next_url = request.POST.get('next') or 'timetracking-list'
        if next_url.startswith('/'):
            return redirect(next_url)
        return redirect(next_url)


class DailyReportView(LoginRequiredMixin, View):
    def get(self, request):
        import datetime as dt_module
        from collections import defaultdict
        from django.utils import timezone
        from jira_integration.models import JiraEvent
        from itsm.models import TicketTag

        schedule = WorkSchedule.objects.filter(user=request.user).first()
        jira_username = schedule.jira_username.strip() if schedule and schedule.jira_username else ''

        # --- Range ---
        range_param = request.GET.get('range', 'today')
        if range_param not in ('today', 'week', 'month', 'custom'):
            range_param = 'today'
        now = timezone.now()
        import zoneinfo as _zi
        try:
            user_tz = _zi.ZoneInfo(schedule.timezone) if schedule and schedule.timezone else dt_module.timezone.utc
        except Exception:
            user_tz = dt_module.timezone.utc
        now_local = now.astimezone(user_tz)

        custom_date_from = ''
        custom_date_to = ''

        if range_param == 'custom':
            try:
                custom_date_from = request.GET.get('date_from', '')
                df = dt_module.date.fromisoformat(custom_date_from)
            except ValueError:
                df = now_local.date()
                custom_date_from = df.isoformat()
                range_param = 'today'
            try:
                custom_date_to = request.GET.get('date_to', '')
                dt_val = dt_module.date.fromisoformat(custom_date_to)
            except ValueError:
                dt_val = df
                custom_date_to = dt_val.isoformat()
            if dt_val < df:
                dt_val = df
                custom_date_to = dt_val.isoformat()
            start_dt = dt_module.datetime(df.year, df.month, df.day, tzinfo=user_tz).astimezone(dt_module.timezone.utc)
            # end of range = end of date_to in user tz
            now = dt_module.datetime(dt_val.year, dt_val.month, dt_val.day,
                                     23, 59, 59, tzinfo=user_tz).astimezone(dt_module.timezone.utc)
            # cap to actual now so we don't show future
            actual_now = timezone.now()
            if now > actual_now:
                now = actual_now
        elif range_param == 'today':
            start_dt = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt_module.timezone.utc)
        elif range_param == 'week':
            start_dt = (now_local - dt_module.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt_module.timezone.utc)
        else:
            start_dt = (now_local - dt_module.timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt_module.timezone.utc)

        def range_seconds(entered_at, exited_at, ongoing_in_progress=False):
            """
            Count seconds from this segment that count toward the selected range.
            Only counts if the transition INTO this status happened within [start_dt, now],
            or if the segment is an ongoing In Progress that started before the range
            (the ticket is actively being worked on).
            """
            if not entered_at:
                return 0
            if entered_at >= start_dt:
                seg_end = min(exited_at or now, now)
                return max(0, int((seg_end - entered_at).total_seconds()))
            if ongoing_in_progress and exited_at is None:
                return max(0, int((now - start_dt).total_seconds()))
            return 0

        def fmt(seconds):
            seconds = max(0, int(seconds))
            hours, rem = divmod(seconds, 3600)
            minutes = rem // 60
            if hours:
                return f"{hours}h {minutes}m"
            return f"{minutes}m"

        my_tickets = []
        if jira_username:
            my_tickets = list(
                JiraTicket.objects.filter(assignee__iexact=jira_username, is_deleted=False).order_by('issue_key')
            )

        # Build raw segments per ticket (single event fetch)
        ticket_segments = {}
        for ticket in my_tickets:
            events = list(JiraEvent.objects.filter(ticket=ticket).order_by('received_at'))
            transitions = []
            for event in events:
                for item in event.payload.get('changelog', {}).get('items', []):
                    if item.get('field') == 'status':
                        transitions.append({
                            'from_status': item.get('fromString', ''),
                            'to_status': item.get('toString', ''),
                            'at': event.received_at,
                        })
            if not transitions:
                ticket_segments[ticket.issue_key] = []
                continue
            segs = [{'status': transitions[0]['from_status'], 'entered_at': None, 'exited_at': transitions[0]['at']}]
            for i, t in enumerate(transitions):
                exited_at = transitions[i + 1]['at'] if i + 1 < len(transitions) else None
                segs.append({'status': t['to_status'], 'entered_at': t['at'], 'exited_at': exited_at})
            ticket_segments[ticket.issue_key] = segs

        # Compute range seconds per segment, respecting the new semantics:
        # - segments entered within the range count normally
        # - ongoing In Progress segments entered before the range count from start_dt
        # - all other pre-range segments contribute 0
        def ticket_seg_secs(ticket):
            is_ip = ticket.status.lower() == 'in progress'
            result = []
            for seg in ticket_segments[ticket.issue_key]:
                if not seg['status'] or not seg['entered_at']:
                    result.append(0)
                    continue
                ongoing_ip = is_ip and seg['exited_at'] is None
                result.append(range_seconds(seg['entered_at'], seg['exited_at'], ongoing_ip))
            return result

        # Per-ticket total range seconds (used for filtering and tag attribution)
        ticket_range_secs = {}
        ticket_seg_secs_map = {}
        for ticket in my_tickets:
            seg_secs = ticket_seg_secs(ticket)
            ticket_seg_secs_map[ticket.issue_key] = seg_secs
            ticket_range_secs[ticket.issue_key] = sum(seg_secs)

        # --- Filters (global — applied to all panels) ---
        selected_tags = request.GET.getlist('tags')
        selected_statuses = request.GET.getlist('statuses')

        # Collect all available tags from active tickets (before tag filter) for the UI
        active_keys_all = [k for k, v in ticket_range_secs.items() if v > 0]
        all_tags = sorted(set(
            tt.tag.name
            for tt in TicketTag.objects.filter(
                ticket__external_id__in=active_keys_all
            ).select_related('tag')
        ))

        # Collect all statuses that have range activity (for status dropdown UI)
        all_statuses = []
        for ticket in my_tickets:
            for seg, secs in zip(ticket_segments[ticket.issue_key], ticket_seg_secs_map[ticket.issue_key]):
                if seg['status'] and secs > 0 and seg['status'] not in all_statuses:
                    all_statuses.append(seg['status'])

        # Apply tag filter: keep only tickets that have ALL selected tags
        if selected_tags:
            tagged_per_tag = []
            for tag_name in selected_tags:
                keys = set(TicketTag.objects.filter(
                    ticket__external_id__in=active_keys_all,
                    tag__name=tag_name,
                ).values_list('ticket__external_id', flat=True))
                tagged_per_tag.append(keys)
            # AND: intersection of all tag sets
            matching_keys = set.intersection(*tagged_per_tag) if tagged_per_tag else set(active_keys_all)
            filtered_tickets = [t for t in my_tickets if t.issue_key in matching_keys]
        else:
            filtered_tickets = [t for t in my_tickets if ticket_range_secs.get(t.issue_key, 0) > 0]

        # Apply status filter: keep only tickets with activity in at least one selected status
        if selected_statuses:
            filtered_tickets = [
                t for t in filtered_tickets
                if any(
                    seg['status'] in selected_statuses and secs > 0
                    for seg, secs in zip(ticket_segments[t.issue_key], ticket_seg_secs_map[t.issue_key])
                )
            ]

        # --- Time by Status (range-scoped, filters applied) ---
        status_seconds = defaultdict(int)
        for ticket in filtered_tickets:
            segs = ticket_segments[ticket.issue_key]
            for seg, secs in zip(segs, ticket_seg_secs_map[ticket.issue_key]):
                if seg['status'] and secs > 0:
                    status_seconds[seg['status']] += secs

        status_totals = [
            {'status': s, 'display': fmt(secs)}
            for s, secs in sorted(status_seconds.items())
            if secs > 0
        ]

        # --- Time by Tag (In Progress only, transitions that started within the range) ---
        # Using all-status time inflates weekly/monthly totals because N concurrent tickets
        # each contribute the full range duration. Only IP segments with entered_at >= start_dt
        # are counted — ongoing IP from before the range contributes 0 here.
        ticket_ip_range_secs = {}
        for ticket in my_tickets:
            segs = ticket_segments[ticket.issue_key]
            secs = sum(
                max(0, int((min(seg['exited_at'] or now, now) - seg['entered_at']).total_seconds()))
                for seg in segs
                if seg['status']
                and seg['status'].lower() == 'in progress'
                and seg['entered_at']
                and seg['entered_at'] >= start_dt
            )
            ticket_ip_range_secs[ticket.issue_key] = secs

        filtered_keys = [t.issue_key for t in filtered_tickets]
        tag_seconds = defaultdict(int)
        for tt in TicketTag.objects.filter(
            ticket__external_id__in=filtered_keys
        ).select_related('tag', 'ticket'):
            secs = ticket_ip_range_secs.get(tt.ticket.external_id, 0)
            if secs > 0:
                tag_seconds[tt.tag.name] += secs
        tag_totals = [
            {'tag': name, 'display': fmt(secs)}
            for name, secs in sorted(tag_seconds.items(), key=lambda x: -x[1])
            if secs > 0
        ]

        # --- In Progress / Now (unaffected by range or tag filter) ---
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_rows = []
        for ticket in my_tickets:
            if ticket.status.lower() != 'in progress':
                continue
            ongoing_seg = next(
                (seg for seg in ticket_segments[ticket.issue_key] if seg['entered_at'] and seg['exited_at'] is None),
                None,
            )
            if ongoing_seg:
                total_secs = int((now - ongoing_seg['entered_at']).total_seconds())
                today_secs = int((now - max(ongoing_seg['entered_at'], today_start)).total_seconds())
            else:
                total_secs = today_secs = 0
            today_rows.append({
                'ticket': ticket,
                'jira_ongoing': fmt(total_secs) if ongoing_seg else '—',
                'jira_today': fmt(today_secs) if ongoing_seg else '—',
            })

        # --- Status history pivot (range-scoped, filters applied) ---
        pivot_rows = []
        for ticket in filtered_tickets:
            by_status = defaultdict(lambda: {'secs': 0, 'ongoing': False})
            segs = ticket_segments[ticket.issue_key]
            for seg, secs in zip(segs, ticket_seg_secs_map[ticket.issue_key]):
                if not seg['status'] or not seg['entered_at'] or secs == 0:
                    continue
                by_status[seg['status']]['secs'] += secs
                if seg['exited_at'] is None:
                    by_status[seg['status']]['ongoing'] = True
            cells = []
            for status in all_statuses:
                entry = by_status.get(status)
                if entry and entry['secs'] > 0:
                    cells.append({'duration': fmt(entry['secs']), 'ongoing': entry['ongoing']})
                else:
                    cells.append({'duration': '—', 'ongoing': False})
            pivot_rows.append({'ticket': ticket, 'cells': cells})

        # --- Gantt timeline ---
        _status_colors = {
            'in progress': '#0d6efd',
            'bloqueado': '#dc3545',
            'blocked': '#dc3545',
            'done': '#198754',
            'backlog': '#6c757d',
            'testing': '#fd7e14',
            'in review': '#6f42c1',
            'review': '#6f42c1',
        }
        _fallback_colors = ['#20c997', '#0dcaf0', '#ffc107', '#d63384', '#adb5bd']
        _fallback_idx = {}

        def status_color(s):
            key = s.lower()
            if key in _status_colors:
                return _status_colors[key]
            if key not in _fallback_idx:
                _fallback_idx[key] = len(_fallback_idx) % len(_fallback_colors)
            return _fallback_colors[_fallback_idx[key]]

        range_total_secs = max(1, (now - start_dt).total_seconds())

        def bar_pos(entered_at, exited_at):
            eff_start = max(entered_at, start_dt)
            eff_end = min(exited_at or now, now)
            left = max(0.0, (eff_start - start_dt).total_seconds() / range_total_secs * 100)
            width = max(0.0, (eff_end - eff_start).total_seconds() / range_total_secs * 100)
            return round(left, 3), round(width, 3)

        _terminal_statuses = {'done', 'closed', 'cancelled', 'canceled', 'resolved', 'cerrado', 'terminado'}

        gantt_rows = []
        for ticket in filtered_tickets:
            bars = []
            for seg in ticket_segments[ticket.issue_key]:
                if not seg['entered_at'] or not seg['status']:
                    continue
                is_terminal = seg['status'].lower() in _terminal_statuses
                if seg['exited_at'] is None and is_terminal:
                    continue
                # When status filter is active, only render bars for selected statuses
                if selected_statuses and seg['status'] not in selected_statuses:
                    continue
                exited = seg['exited_at'] or now
                if seg['entered_at'] >= now or exited <= start_dt:
                    continue
                left, width = bar_pos(seg['entered_at'], seg['exited_at'])
                if width < 0.05:
                    continue
                bars.append({
                    'status': seg['status'],
                    'color': status_color(seg['status']),
                    'left': left,
                    'width': width,
                    'ongoing': seg['exited_at'] is None,
                })
            if bars:
                gantt_rows.append({'ticket': ticket, 'bars': bars})

        # X axis ticks
        # Gantt tick strategy: today or single-day custom → hourly; week or multi-day custom → daily; month → every 3 days
        _custom_single_day = (range_param == 'custom' and custom_date_from == custom_date_to)
        _custom_multi_day = (range_param == 'custom' and custom_date_from != custom_date_to)
        _range_days = max(1, (now - start_dt).days)

        gantt_ticks = []
        if range_param == 'today' or _custom_single_day:
            tick = start_dt
            while tick <= now:
                left = (tick - start_dt).total_seconds() / range_total_secs * 100
                gantt_ticks.append({'label': tick.astimezone(user_tz).strftime('%H:%M'), 'left': round(left, 2)})
                tick += datetime.timedelta(hours=2)
        elif range_param == 'week' or _custom_multi_day:
            tick = start_dt
            while tick <= now:
                left = (tick - start_dt).total_seconds() / range_total_secs * 100
                gantt_ticks.append({'label': tick.astimezone(user_tz).strftime('%a %d'), 'left': round(left, 2)})
                tick += datetime.timedelta(days=1)
        else:
            tick = start_dt
            while tick <= now:
                left = (tick - start_dt).total_seconds() / range_total_secs * 100
                gantt_ticks.append({'label': tick.astimezone(user_tz).strftime('%d/%m'), 'left': round(left, 2)})
                tick += datetime.timedelta(days=3)

        # Working hour boundary lines on the Gantt (dashed vertical lines at start/end of each working day)
        work_lines = []
        if schedule and schedule.start_time and schedule.end_time:
            _weekday_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
            d = start_dt.astimezone(user_tz).date()
            end_date = now.astimezone(user_tz).date()
            while d <= end_date:
                if getattr(schedule, _weekday_map[d.weekday()], False):
                    ws = dt_module.datetime(d.year, d.month, d.day,
                                            schedule.start_time.hour, schedule.start_time.minute,
                                            tzinfo=user_tz).astimezone(dt_module.timezone.utc)
                    we = dt_module.datetime(d.year, d.month, d.day,
                                            schedule.end_time.hour, schedule.end_time.minute,
                                            tzinfo=user_tz).astimezone(dt_module.timezone.utc)
                    if start_dt <= ws <= now:
                        left = (ws - start_dt).total_seconds() / range_total_secs * 100
                        work_lines.append({'left': round(left, 3)})
                    if start_dt <= we <= now:
                        left = (we - start_dt).total_seconds() / range_total_secs * 100
                        work_lines.append({'left': round(left, 3)})
                d += dt_module.timedelta(days=1)

        # Color legend (unique statuses across all gantt bars)
        seen = {}
        for row in gantt_rows:
            for bar in row['bars']:
                if bar['status'] not in seen:
                    seen[bar['status']] = bar['color']
        gantt_legend = [{'status': s, 'color': c} for s, c in seen.items()]

        return render(request, 'timetracking/report.html', {
            'status_totals': status_totals,
            'today_rows': today_rows,
            'pivot_rows': pivot_rows,
            'all_statuses': all_statuses,
            'jira_username': jira_username,
            'range_param': range_param,
            'tag_totals': tag_totals,
            'selected_tags': selected_tags,
            'all_tags': all_tags,
            'selected_statuses': selected_statuses,
            'gantt_rows': gantt_rows,
            'gantt_ticks': gantt_ticks,
            'gantt_legend': gantt_legend,
            'work_lines': work_lines,
            'custom_date_from': custom_date_from,
            'custom_date_to': custom_date_to,
        })


class WorkScheduleView(LoginRequiredMixin, View):
    DAYS = [
        ('mon', 'Monday'),
        ('tue', 'Tuesday'),
        ('wed', 'Wednesday'),
        ('thu', 'Thursday'),
        ('fri', 'Friday'),
        ('sat', 'Saturday'),
        ('sun', 'Sunday'),
    ]

    def _get_or_create(self, user):
        schedule, _ = WorkSchedule.objects.get_or_create(user=user)
        return schedule

    def get(self, request):
        return redirect('settings-user')

    def post(self, request):
        schedule = self._get_or_create(request.user)
        for attr, _ in self.DAYS:
            setattr(schedule, attr, attr in request.POST)
        schedule.jira_username = request.POST.get('jira_username', '').strip()
        tz = request.POST.get('timezone', 'UTC').strip() or 'UTC'
        try:
            import zoneinfo
            zoneinfo.ZoneInfo(tz)
            schedule.timezone = tz
        except (zoneinfo.ZoneInfoNotFoundError, KeyError):
            messages.error(request, f'Invalid timezone: {tz}')
            return self._render(request, schedule)
        start = request.POST.get('start_time', '').strip()
        end = request.POST.get('end_time', '').strip()
        import datetime as dt
        try:
            schedule.start_time = dt.time.fromisoformat(start)
        except ValueError:
            messages.error(request, 'Hora de inicio inválida.')
            return self._render(request, schedule)
        try:
            schedule.end_time = dt.time.fromisoformat(end)
        except ValueError:
            messages.error(request, 'Hora de fin inválida.')
            return self._render(request, schedule)
        if schedule.start_time >= schedule.end_time:
            messages.error(request, 'La hora de fin debe ser posterior a la de inicio.')
            return self._render(request, schedule)
        schedule.save()
        messages.success(request, 'Horario guardado.')
        return redirect('settings-user')

    def _render(self, request, schedule):
        active_days = {attr for attr, _ in self.DAYS if getattr(schedule, attr)}
        return render(request, 'timetracking/schedule_form.html', {
            'schedule': schedule,
            'days': self.DAYS,
            'active_days': active_days,
        })


class TicketTimelineView(LoginRequiredMixin, View):
    def get(self, request, issue_key):
        import datetime as dt_module
        import zoneinfo as _zi
        from collections import defaultdict
        from django.utils import timezone

        ticket = get_object_or_404(JiraTicket, issue_key=issue_key)

        schedule = WorkSchedule.objects.filter(user=request.user).first()
        try:
            user_tz = _zi.ZoneInfo(schedule.timezone) if schedule and schedule.timezone else _zi.ZoneInfo('UTC')
        except Exception:
            user_tz = _zi.ZoneInfo('UTC')

        now = timezone.now()
        today_local = now.astimezone(user_tz).date()

        date_from_str = request.GET.get('date_from', '')
        date_to_str = request.GET.get('date_to', '')
        try:
            date_from = dt_module.date.fromisoformat(date_from_str)
        except ValueError:
            date_from = today_local
        try:
            date_to = dt_module.date.fromisoformat(date_to_str)
        except ValueError:
            date_to = today_local

        if date_to < date_from:
            date_to = date_from

        # Convert local date range to UTC-aware boundaries
        start_dt = dt_module.datetime(date_from.year, date_from.month, date_from.day,
                                      tzinfo=user_tz).astimezone(dt_module.timezone.utc)
        end_dt = dt_module.datetime(date_to.year, date_to.month, date_to.day,
                                    tzinfo=user_tz) + dt_module.timedelta(days=1)
        end_dt = end_dt.astimezone(dt_module.timezone.utc)

        # Fetch all Jira events for this ticket (all time — needed to compute status durations)
        all_events = list(JiraEvent.objects.filter(ticket=ticket).order_by('received_at'))

        def fmt(seconds):
            seconds = max(0, int(seconds))
            h, rem = divmod(seconds, 3600)
            m = rem // 60
            if h:
                return f"{h}h {m}m"
            return f"{m}m"

        # Build status segments across all time (for duration calculation)
        raw_transitions = []
        for event in all_events:
            for item in event.payload.get('changelog', {}).get('items', []):
                if item.get('field') == 'status':
                    raw_transitions.append({'to_status': item.get('toString', ''), 'at': event.received_at})

        segments = {}  # entered_at → {status, exited_at}
        for i, t in enumerate(raw_transitions):
            exited_at = raw_transitions[i + 1]['at'] if i + 1 < len(raw_transitions) else None
            segments[t['at']] = {'status': t['to_status'], 'exited_at': exited_at}

        # Build timeline: all activity events within the date range
        timeline = []
        status_seconds = defaultdict(int)

        for event in all_events:
            if event.received_at < start_dt or event.received_at >= end_dt:
                continue
            at_local = event.received_at.astimezone(user_tz)
            items = event.payload.get('changelog', {}).get('items', [])
            for item in items:
                field = item.get('field', '')
                if field == 'status':
                    seg = segments.get(event.received_at)
                    if seg:
                        exited = seg['exited_at'] or now
                        effective_start = max(event.received_at, start_dt)
                        effective_end = min(exited, now)
                        secs = max(0, int((effective_end - effective_start).total_seconds()))
                        ongoing = seg['exited_at'] is None
                        status_seconds[seg['status']] += secs
                        timeline.append({
                            'type': 'transition',
                            'at': at_local,
                            'from_status': item.get('fromString', ''),
                            'status': seg['status'],
                            'duration': fmt(secs),
                            'ongoing': ongoing,
                            'sort_key': event.received_at,
                        })
                else:
                    from_val = item.get('fromString') or item.get('from') or ''
                    to_val = item.get('toString') or item.get('to') or ''
                    timeline.append({
                        'type': 'activity',
                        'at': at_local,
                        'field': field,
                        'from_val': from_val,
                        'to_val': to_val,
                        'sort_key': event.received_at,
                    })

        # Fetch manual TimeEntry records in the date range
        manual_entries = list(
            TimeEntry.objects.filter(
                user=request.user,
                jira_ticket=ticket,
                date__gte=date_from,
                date__lte=date_to,
            ).order_by('date', 'created_at')
        )
        total_manual_minutes = 0
        for entry in manual_entries:
            total_manual_minutes += entry.minutes
            timeline.append({
                'type': 'manual',
                'at': dt_module.datetime(entry.date.year, entry.date.month, entry.date.day, tzinfo=user_tz),
                'entry': entry,
                'sort_key': dt_module.datetime(entry.date.year, entry.date.month, entry.date.day,
                                               tzinfo=user_tz).astimezone(dt_module.timezone.utc),
            })

        timeline.sort(key=lambda x: x['sort_key'])

        status_totals = [
            {'status': s, 'display': fmt(secs)}
            for s, secs in sorted(status_seconds.items())
            if secs > 0
        ]

        back_range = request.GET.get('back_range', 'today')
        back_tags = request.GET.getlist('back_tags')
        back_statuses = request.GET.getlist('back_statuses')

        return render(request, 'timetracking/ticket_timeline.html', {
            'ticket': ticket,
            'date_from': date_from.isoformat(),
            'date_to': date_to.isoformat(),
            'timeline': timeline,
            'status_totals': status_totals,
            'total_manual_minutes': total_manual_minutes,
            'total_manual_display': fmt(total_manual_minutes * 60),
            'back_range': back_range,
            'back_tags': back_tags,
            'back_statuses': back_statuses,
        })
