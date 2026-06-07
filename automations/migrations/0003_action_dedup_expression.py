from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('automations', '0002_remove_trigger_event_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='action',
            name='dedup_expression',
            field=models.CharField(
                blank=True,
                max_length=500,
                help_text='JSONPath to extract a unique key from the payload (e.g. $.issue.key). If set, an existing ticket with that key is updated instead of creating a new one.',
            ),
        ),
    ]
