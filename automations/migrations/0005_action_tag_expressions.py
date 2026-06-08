from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('automations', '0004_action_description_format'),
    ]

    operations = [
        migrations.AddField(
            model_name='action',
            name='tag_expressions',
            field=models.TextField(
                blank=True,
                help_text='One JSONPath expression per line. Each resolved value becomes a tag name on the ticket.',
            ),
        ),
    ]
