from django.db import migrations, models


def backfill_assignee(apps, schema_editor):
    JiraTicket = apps.get_model('jira_integration', 'JiraTicket')
    JiraEvent = apps.get_model('jira_integration', 'JiraEvent')
    for ticket in JiraTicket.objects.all():
        event = (
            JiraEvent.objects.filter(ticket=ticket)
            .order_by('-received_at')
            .first()
        )
        if not event:
            continue
        assignee = (
            event.payload
            .get('issue', {})
            .get('fields', {})
            .get('assignee') or {}
        )
        display_name = assignee.get('displayName', '')
        if display_name:
            ticket.assignee = display_name
            ticket.save(update_fields=['assignee'])


class Migration(migrations.Migration):

    dependencies = [
        ('jira_integration', '0002_jiraticket_labels'),
    ]

    operations = [
        migrations.AddField(
            model_name='jiraticket',
            name='assignee',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.RunPython(backfill_assignee, migrations.RunPython.noop),
    ]
