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
    from vault.models import Credential
    itsm_count = Ticket.objects.exclude(state__in=['closed', 'cancelled']).count()
    jira_count = JiraTicket.objects.count()
    automations_count = Trigger.objects.filter(is_active=True).count()
    vault_count = Credential.objects.filter(owner=request.user).count() if request.user.is_authenticated else 0
    return render(request, 'core/dashboard.html', {
        'itsm_count': itsm_count,
        'jira_count': jira_count,
        'automations_count': automations_count,
        'vault_count': vault_count,
    })


def health(request):
    try:
        from django.db import connection
        connection.ensure_connection()
        return JsonResponse({'status': 'ok'})
    except Exception:
        return JsonResponse({'status': 'error'}, status=503)
