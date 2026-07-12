# Team moves here from vault (v5.10.4) — app-wide by location, even though
# vault remains its only consumer today. State-only move: db_table is
# pinned to the original vault_team/vault_team_members names, so
# database_operations is empty — the physical tables already exist and
# must not be touched by this migration. See .claude/v5.10.4.md.

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_userprofile_avatar'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name='Team',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('name', models.CharField(max_length=100, unique=True)),
                        ('code', models.SlugField(blank=True, max_length=50, unique=True)),
                        ('description', models.TextField(blank=True, default='')),
                        ('members', models.ManyToManyField(blank=True, db_table='vault_team_members', related_name='vault_teams', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'db_table': 'vault_team',
                        'ordering': ['name'],
                    },
                ),
            ],
        ),
    ]
