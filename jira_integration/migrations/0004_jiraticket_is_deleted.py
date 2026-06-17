from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jira_integration', '0003_jiraticket_assignee'),
    ]

    operations = [
        migrations.AddField(
            model_name='jiraticket',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
    ]
