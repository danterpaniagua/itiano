from django.db import migrations

# (status name, category, closed). Same defaults the PostgreSQL-era migrations seeded.
DEFAULTS = [
    ('In Progress', 'in_progress', False),
    ('En curso', 'in_progress', False),
    ('Done', 'done', True),
    ('Descartado', 'done', True),
    ('Bloqueado', 'blocked', False),
    ('Testing', 'testing', False),
    ('Backlog', 'backlog', False),
    ('Selected for Development', 'other', False),
]


def seed_defaults(apps, schema_editor):
    JiraStatusConfig = apps.get_model('settings_hub', 'JiraStatusConfig')
    for name, category, is_terminal in DEFAULTS:
        JiraStatusConfig.objects.get_or_create(
            status_name=name, defaults={'category': category, 'is_terminal': is_terminal},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('settings_hub', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_defaults, migrations.RunPython.noop),
    ]
