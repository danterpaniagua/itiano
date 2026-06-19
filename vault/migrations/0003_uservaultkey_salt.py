from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vault', '0002_credentialversion'),
    ]

    operations = [
        migrations.AddField(
            model_name='uservaultkey',
            name='salt',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
    ]
