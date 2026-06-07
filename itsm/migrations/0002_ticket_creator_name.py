from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('itsm', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='creator_name',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
