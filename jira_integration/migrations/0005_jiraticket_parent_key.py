from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jira_integration', '0004_jiraticket_is_deleted'),
    ]

    operations = [
        migrations.AddField(
            model_name='jiraticket',
            name='parent_key',
            field=models.CharField(blank=True, max_length=50),
        ),
    ]
