from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('timetracking', '0002_workschedule'),
    ]

    operations = [
        migrations.AddField(
            model_name='workschedule',
            name='jira_username',
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
