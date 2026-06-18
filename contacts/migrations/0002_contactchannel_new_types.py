from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='contactchannel',
            name='type',
            field=models.CharField(
                max_length=10,
                choices=[
                    ('email', 'Email'),
                    ('post', 'POST'),
                    ('phone', 'Phone'),
                    ('hangouts', 'Hangouts'),
                    ('jira', 'Jira'),
                    ('telegram', 'Telegram'),
                ],
            ),
        ),
    ]
