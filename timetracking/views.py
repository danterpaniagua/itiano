import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from jira_integration.models import JiraTicket

from .models import TimeEntry


class TimeEntryListView(LoginRequiredMixin, View):
    def get(self, request):
        entries = TimeEntry.objects.filter(user=request.user).select_related('jira_ticket')
        ticket_filter = request.GET.get('ticket', '').strip()
        if ticket_filter:
            entries = entries.filter(jira_ticket__issue_key__icontains=ticket_filter)
        return render(request, 'timetracking/entry_list.html', {
            'entries': entries,
            'ticket_filter': ticket_filter,
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
        entries = TimeEntry.objects.filter(user=request.user).select_related('jira_ticket').order_by('date', 'jira_ticket__issue_key')

        # Group by date
        from collections import defaultdict
        days = defaultdict(list)
        day_totals = defaultdict(int)
        for entry in entries:
            days[entry.date].append(entry)
            day_totals[entry.date] += entry.minutes

        report = []
        for date in sorted(days.keys(), reverse=True):
            total = day_totals[date]
            h, m = divmod(total, 60)
            report.append({
                'date': date,
                'entries': days[date],
                'total_minutes': total,
                'total_display': f"{h}h {m}m" if m else f"{h}h",
            })

        return render(request, 'timetracking/report.html', {'report': report})
