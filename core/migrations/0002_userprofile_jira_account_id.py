from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='jira_account_id',
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
