from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('itsm', '0005_ticket_external_id'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ticketevent',
            name='old_value',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='ticketevent',
            name='new_value',
            field=models.TextField(blank=True),
        ),
    ]
