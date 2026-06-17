import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from jira_integration.models import JiraTicket

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
        if range_param not in ('today', 'week', 'month'):
            range_param = 'today'
        now = timezone.now()
        if range_param == 'today':
            start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif range_param == 'week':
            start_dt = (now - dt_module.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start_dt = (now - dt_module.timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)

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
            days, rem = divmod(seconds, 86400)
            hours, rem = divmod(rem, 3600)
            minutes = rem // 60
            if days:
                return f"{days}d {hours}h {minutes}m"
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

        # --- Tag filter (global — filters all panels) ---
        selected_tags = request.GET.getlist('tags')

        # Collect all available tags from active tickets (before tag filter) for the UI
        active_keys_all = [k for k, v in ticket_range_secs.items() if v > 0]
        all_tags = sorted(set(
            tt.tag.name
            for tt in TicketTag.objects.filter(
                ticket__external_id__in=active_keys_all
            ).select_related('tag')
        ))

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

        # --- Time by Status (range-scoped, tag-filtered) ---
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

        # --- Time by Tag (range-scoped, tag-filtered) ---
        filtered_keys = [t.issue_key for t in filtered_tickets]
        tag_seconds = defaultdict(int)
        for tt in TicketTag.objects.filter(
            ticket__external_id__in=filtered_keys
        ).select_related('tag', 'ticket'):
            tag_seconds[tt.tag.name] += ticket_range_secs.get(tt.ticket.external_id, 0)
        tag_totals = [
            {'tag': name, 'display': fmt(secs)}
            for name, secs in sorted(tag_seconds.items(), key=lambda x: -x[1])
            if secs > 0
        ]

        # --- In Progress / Now (unaffected by range or tag filter) ---
        today_rows = []
        for ticket in my_tickets:
            if ticket.status.lower() != 'in progress':
                continue
            ongoing_seg = next(
                (seg for seg in ticket_segments[ticket.issue_key] if seg['entered_at'] and seg['exited_at'] is None),
                None,
            )
            duration = fmt(int((now - ongoing_seg['entered_at']).total_seconds())) if ongoing_seg else '—'
            today_rows.append({'ticket': ticket, 'jira_ongoing': duration})

        # --- Status history pivot (range-scoped, tag-filtered) ---
        all_statuses = []
        for segs in ticket_segments.values():
            for seg in segs:
                if seg['status'] and seg['status'] not in all_statuses:
                    all_statuses.append(seg['status'])

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
        schedule = self._get_or_create(request.user)
        active_days = {attr for attr, _ in self.DAYS if getattr(schedule, attr)}
        return render(request, 'timetracking/schedule_form.html', {
            'schedule': schedule,
            'days': self.DAYS,
            'active_days': active_days,
        })

    def post(self, request):
        schedule = self._get_or_create(request.user)
        for attr, _ in self.DAYS:
            setattr(schedule, attr, attr in request.POST)
        schedule.jira_username = request.POST.get('jira_username', '').strip()
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
        return redirect('timetracking-schedule')

    def _render(self, request, schedule):
        active_days = {attr for attr, _ in self.DAYS if getattr(schedule, attr)}
        return render(request, 'timetracking/schedule_form.html', {
            'schedule': schedule,
            'days': self.DAYS,
            'active_days': active_days,
        })
