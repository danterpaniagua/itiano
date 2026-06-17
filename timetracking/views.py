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
        from collections import defaultdict
        from jira_integration.models import JiraEvent
        from jira_integration.views import _build_status_timeline

        schedule = WorkSchedule.objects.filter(user=request.user).first()
        jira_username = schedule.jira_username.strip() if schedule and schedule.jira_username else ''

        my_tickets = []
        if jira_username:
            my_tickets = list(
                JiraTicket.objects.filter(assignee__iexact=jira_username).order_by('issue_key')
            )

        # Build timeline per ticket
        timelines = {}
        for ticket in my_tickets:
            events = list(JiraEvent.objects.filter(ticket=ticket).order_by('received_at'))
            timelines[ticket.issue_key] = _build_status_timeline(ticket, events)

        # --- C: total seconds per status across all tickets ---
        status_seconds = defaultdict(int)
        for issue_key, timeline in timelines.items():
            for row in timeline:
                if not row['status']:
                    continue
                secs = int(row.get('_seconds', 0))
                status_seconds[row['status']] += secs

        # Recompute timelines with raw seconds for totals
        status_seconds = defaultdict(int)
        from django.utils import timezone
        now = timezone.now()
        for ticket in my_tickets:
            events = list(JiraEvent.objects.filter(ticket=ticket).order_by('received_at'))
            transitions = []
            for event in sorted(events, key=lambda e: e.received_at):
                items = event.payload.get('changelog', {}).get('items', [])
                for item in items:
                    if item.get('field') == 'status':
                        transitions.append({'from_status': item.get('fromString', ''), 'to_status': item.get('toString', ''), 'at': event.received_at})
            if not transitions:
                continue
            segments = [{'status': transitions[0]['from_status'], 'entered_at': None, 'exited_at': transitions[0]['at']}]
            for i, t in enumerate(transitions):
                exited_at = transitions[i + 1]['at'] if i + 1 < len(transitions) else None
                segments.append({'status': t['to_status'], 'entered_at': t['at'], 'exited_at': exited_at})
            for seg in segments:
                if not seg['status'] or not seg['entered_at']:
                    continue
                end = seg['exited_at'] or now
                status_seconds[seg['status']] += int((end - seg['entered_at']).total_seconds())

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

        status_totals = [
            {'status': s, 'display': fmt(secs)}
            for s, secs in sorted(status_seconds.items())
        ]

        # --- A: active In Progress tickets with ongoing duration ---
        today_rows = []
        for ticket in my_tickets:
            if ticket.status.lower() != 'in progress':
                continue
            timeline = timelines[ticket.issue_key]
            ongoing = next((r for r in timeline if r.get('ongoing')), None)
            today_rows.append({
                'ticket': ticket,
                'jira_ongoing': ongoing['duration'] if ongoing else '—',
            })

        # --- B: pivot all tickets × all statuses ---
        all_statuses = []
        for timeline in timelines.values():
            for row in timeline:
                if row['status'] and row['status'] not in all_statuses:
                    all_statuses.append(row['status'])

        pivot_rows = []
        for ticket in my_tickets:
            timeline = timelines[ticket.issue_key]
            if not timeline:
                continue
            by_status = {row['status']: row for row in timeline}
            cells = []
            for status in all_statuses:
                entry = by_status.get(status)
                cells.append({
                    'duration': entry['duration'] if entry else '—',
                    'ongoing': entry['ongoing'] if entry else False,
                })
            pivot_rows.append({'ticket': ticket, 'cells': cells})

        return render(request, 'timetracking/report.html', {
            'status_totals': status_totals,
            'today_rows': today_rows,
            'pivot_rows': pivot_rows,
            'all_statuses': all_statuses,
            'jira_username': jira_username,
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
