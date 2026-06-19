from django.db import migrations, models


def backfill_account_id(apps, schema_editor):
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
        assignee_obj = (
            event.payload.get('issue', {}).get('fields', {}).get('assignee') or {}
        )
        account_id = assignee_obj.get('accountId', '')
        if account_id:
            ticket.assignee_account_id = account_id[:100]
            ticket.save(update_fields=['assignee_account_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('jira_integration', '0006_backfill_parent_key'),
    ]

    operations = [
        migrations.AddField(
            model_name='jiraticket',
            name='assignee_account_id',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.RunPython(backfill_account_id, migrations.RunPython.noop),
    ]
