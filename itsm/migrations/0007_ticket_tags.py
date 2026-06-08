import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('itsm', '0006_ticketevent_text_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='Tag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='TicketTag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(
                    choices=[('manual', 'Manual'), ('automation', 'Automation')],
                    default='manual',
                    max_length=20,
                )),
                ('tag', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='ticket_tags',
                    to='itsm.tag',
                )),
                ('ticket', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='ticket_tags',
                    to='itsm.ticket',
                )),
            ],
            options={'unique_together': {('ticket', 'tag')}},
        ),
        migrations.AddField(
            model_name='ticket',
            name='tags',
            field=models.ManyToManyField(
                blank=True,
                related_name='tickets',
                through='itsm.TicketTag',
                to='itsm.tag',
            ),
        ),
    ]
