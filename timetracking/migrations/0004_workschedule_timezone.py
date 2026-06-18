from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('timetracking', '0003_workschedule_jira_username'),
    ]

    operations = [
        migrations.AddField(
            model_name='workschedule',
            name='timezone',
            field=models.CharField(default='UTC', max_length=64),
        ),
    ]
