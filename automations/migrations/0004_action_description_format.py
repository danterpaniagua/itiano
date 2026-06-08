from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('automations', '0003_action_dedup_expression'),
    ]

    operations = [
        migrations.AddField(
            model_name='action',
            name='description_format',
            field=models.CharField(
                choices=[('raw', 'Plain text'), ('html', 'HTML'), ('markdown', 'Markdown')],
                default='raw',
                help_text='Format of the description field in the incoming payload.',
                max_length=10,
            ),
        ),
    ]
