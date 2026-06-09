from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('itsm', '0008_ticketattachment'),
    ]

    operations = [
        migrations.AddField(
            model_name='tag',
            name='color',
            field=models.CharField(blank=True, default='', max_length=7),
        ),
    ]
