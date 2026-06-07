from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('itsm', '0004_ticketevent_field_change'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='external_id',
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
    ]
