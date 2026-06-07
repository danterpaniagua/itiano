from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('automations', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='trigger',
            name='event_type',
        ),
    ]
