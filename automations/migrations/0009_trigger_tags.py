from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('automations', '0008_action_tag_expressions_json'),
        ('itsm', '0009_tag_color'),
    ]

    operations = [
        migrations.AddField(
            model_name='trigger',
            name='tag',
            field=models.ForeignKey(
                blank=True,
                help_text='Tag stamped on every ticket created by this trigger.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='triggers',
                to='itsm.tag',
            ),
        ),
    ]
