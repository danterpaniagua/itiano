from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from itsm.models import Ticket
from jira_integration.models import JiraTicket


@login_required
def dashboard(request):
    itsm_count = Ticket.objects.exclude(state__in=['closed', 'cancelled']).count()
    jira_count = JiraTicket.objects.count()
    return render(request, 'core/dashboard.html', {
        'itsm_count': itsm_count,
        'jira_count': jira_count,
    })
