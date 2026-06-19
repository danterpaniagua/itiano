from django.db import migrations, models


DEFAULTS = [
    ('In Progress',             'in_progress'),
    ('En curso',                'in_progress'),
    ('Done',                    'done'),
    ('Descartado',              'done'),
    ('Bloqueado',               'blocked'),
    ('Testing',                 'testing'),
    ('Backlog',                 'backlog'),
    ('Selected for Development','other'),
]


def seed_defaults(apps, schema_editor):
    JiraStatusConfig = apps.get_model('settings_hub', 'JiraStatusConfig')
    for name, cat in DEFAULTS:
        JiraStatusConfig.objects.get_or_create(status_name=name, defaults={'category': cat})


class Migration(migrations.Migration):

    dependencies = [
        ('settings_hub', '0001_appsetting'),
    ]

    operations = [
        migrations.CreateModel(
            name='JiraStatusConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status_name', models.CharField(max_length=100, unique=True)),
                ('category', models.CharField(
                    choices=[
                        ('in_progress', 'In Progress'),
                        ('blocked',     'Blocked'),
                        ('done',        'Done'),
                        ('testing',     'Testing'),
                        ('backlog',     'Backlog'),
                        ('other',       'Other'),
                    ],
                    default='other',
                    max_length=30,
                )),
            ],
            options={
                'verbose_name': 'Jira Status Config',
                'verbose_name_plural': 'Jira Status Configs',
                'ordering': ['category', 'status_name'],
            },
        ),
        migrations.RunPython(seed_defaults, migrations.RunPython.noop),
    ]
