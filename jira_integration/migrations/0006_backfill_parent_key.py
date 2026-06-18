from django.db import migrations


def backfill_parent_key(apps, schema_editor):
    JiraTicket = apps.get_model('jira_integration', 'JiraTicket')
    JiraEvent = apps.get_model('jira_integration', 'JiraEvent')
    for ticket in JiraTicket.objects.filter(parent_key=''):
        latest = JiraEvent.objects.filter(ticket=ticket).order_by('-received_at').first()
        if not latest:
            continue
        parent = (latest.payload.get('issue') or {}).get('fields', {}).get('parent') or {}
        key = parent.get('key', '')
        if key:
            ticket.parent_key = key
            ticket.save(update_fields=['parent_key'])


class Migration(migrations.Migration):

    dependencies = [
        ('jira_integration', '0005_jiraticket_parent_key'),
    ]

    operations = [
        migrations.RunPython(backfill_parent_key, migrations.RunPython.noop),
    ]
