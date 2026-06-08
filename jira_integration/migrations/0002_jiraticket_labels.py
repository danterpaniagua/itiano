from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jira_integration', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='jiraticket',
            name='labels',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
