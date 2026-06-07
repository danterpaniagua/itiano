from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('itsm', '0002_ticket_creator_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='service',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='ticket',
            name='sub_service',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
