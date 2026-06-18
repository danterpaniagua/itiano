from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from automations.models import Trigger
from itsm.models import Ticket
from jira_integration.models import JiraTicket


@login_required
def docs(request):
    return render(request, 'core/docs.html')


@login_required
def dashboard(request):
    import datetime
    from vault.models import Credential
    from notes.models import Note
    from contacts.models import Contact
    from timetracking.models import TimeEntry
    itsm_count = Ticket.objects.exclude(state__in=['closed', 'cancelled']).count()
    jira_count = JiraTicket.objects.count()
    automations_count = Trigger.objects.filter(is_active=True).count()
    vault_count = Credential.objects.filter(owner=request.user).count() if request.user.is_authenticated else 0
    notes_count = Note.objects.filter(owner=request.user).count() if request.user.is_authenticated else 0
    contacts_count = Contact.objects.count() if request.user.is_staff else 0
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())
    from django.db.models import Sum
    qs = TimeEntry.objects.filter(user=request.user)
    today_minutes = qs.filter(date=today).aggregate(total=Sum('minutes'))['total'] or 0
    weekly_minutes = qs.filter(date__gte=week_start, date__lte=today).aggregate(total=Sum('minutes'))['total'] or 0
    today_hours = today_minutes / 60
    weekly_hours = weekly_minutes / 60
    return render(request, 'core/dashboard.html', {
        'itsm_count': itsm_count,
        'jira_count': jira_count,
        'automations_count': automations_count,
        'vault_count': vault_count,
        'notes_count': notes_count,
        'contacts_count': contacts_count,
        'today_hours': today_hours,
        'weekly_hours': weekly_hours,
    })


@login_required
def profile(request):
    contact = getattr(request.user, 'contact', None)
    return render(request, 'core/profile.html', {'contact': contact})


def health(request):
    try:
        from django.db import connection
        connection.ensure_connection()
        return JsonResponse({'status': 'ok'})
    except Exception:
        return JsonResponse({'status': 'error'}, status=503)
