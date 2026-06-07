from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('itsm', '0003_ticket_service_sub_service'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticketevent',
            name='field_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='ticketevent',
            name='old_value',
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name='ticketevent',
            name='new_value',
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
