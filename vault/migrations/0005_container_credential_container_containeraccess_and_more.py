import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def migrate_team_credentials_into_containers(apps, schema_editor):
    """For each Team with existing visibility='team' credentials, create a
    Container named after the team, grant that team read_write access, and
    re-encrypt those credentials' secrets from team-key (v5.10.0) to
    container-key. Defensive per-credential: decrypt_for_team assumes the
    credential's owner still holds a TeamKeyWrap for the team (i.e. is
    still a member) — nothing in the app enforces that stays true after the
    credential was created, so a failure here is logged and that one
    credential is skipped (left un-migrated, container stays None) rather
    than aborting the whole batch.

    Queries via apps.get_model throughout (historical state — Credential's
    live shape has fields added by later migrations, like is_deleted/
    encrypted_notes, that don't exist in the DB yet at this point in a
    fresh replay; Team specifically moved out of vault.models entirely in
    v5.10.4). Anything passed into a vault.crypto function is re-fetched as
    a live-typed instance first — those functions query live models
    (TeamKeyWrap now points to core.Team, ContainerKeyWrap points to the
    still-in-vault but live Container class), which reject historical
    apps.get_model instances of the "same" model as a type mismatch. Fixed
    retroactively in v5.10.4 — this bug predates the Team move and was only
    ever exercised via manage.py migrate against an incrementally-applied
    dev DB, never a from-scratch replay (manage.py test), until now.
    """
    from django.contrib.auth.models import User
    from core.models import Team as LiveTeam
    from vault.crypto import decrypt_for_team, encrypt_for_container
    from vault.models import Container as LiveContainer
    Container = apps.get_model('vault', 'Container')
    ContainerAccess = apps.get_model('vault', 'ContainerAccess')
    Credential = apps.get_model('vault', 'Credential')
    Team = apps.get_model('vault', 'Team')

    secret_fields = ['encrypted_password', 'encrypted_private_key', 'encrypted_passphrase']

    for team in Team.objects.all():
        team_credentials = Credential.objects.filter(team=team, visibility='team')
        if not team_credentials.exists():
            continue

        container = Container.objects.create(name=team.name, created_by=None)
        ContainerAccess.objects.create(
            container=container, team=team, access_level='read_write',
        )
        live_team = LiveTeam.objects.get(pk=team.pk)
        live_container = LiveContainer.objects.get(pk=container.pk)

        for credential in team_credentials:
            try:
                owner = User.objects.get(pk=credential.owner_id)
                updates = {'container_id': container.pk}
                for field in secret_fields:
                    token = getattr(credential, field)
                    if token:
                        plaintext = decrypt_for_team(live_team, owner, token)
                        updates[field] = encrypt_for_container(live_container, owner, plaintext)
                Credential.objects.filter(pk=credential.pk).update(**updates)
            except Exception as exc:
                print(
                    f'  [v5.10.1 migration] WARNING: could not migrate credential '
                    f'{credential.pk} ({credential.name!r}) for team {team.name!r} '
                    f'into a container — left un-migrated. Reason: {exc}'
                )


def reverse_migrate_team_credentials_into_containers(apps, schema_editor):
    raise migrations.exceptions.IrreversibleError(
        'Cannot reverse container-key re-encryption: the container key that '
        'would be needed is only recoverable through ContainerKeyWrap rows, '
        'which a schema-level reversal would drop first. Restore from a '
        'backup taken before this migration instead.'
    )


class Migration(migrations.Migration):

    dependencies = [
        ('vault', '0004_team_code_team_description_teamkeywrap'),
        # Transitively true via vault's 0004 already, but explicit here too
        # since this migration's RunPython also imports core.models.Team
        # live (see v5.10.4 fix note above).
        ('core', '0004_team'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Container',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('parent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='children', to='vault.container')),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='credential',
            name='container',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='credentials', to='vault.container'),
        ),
        migrations.CreateModel(
            name='ContainerAccess',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('access_level', models.CharField(choices=[('read', 'Read'), ('read_write', 'Read/Write')], default='read', max_length=10)),
                ('container', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='access_grants', to='vault.container')),
                ('team', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='container_access_grants', to='vault.team')),
            ],
            options={
                'unique_together': {('container', 'team')},
            },
        ),
        migrations.CreateModel(
            name='ContainerKeyWrap',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('wrapped_key', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('container', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='key_wraps', to='vault.container')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='container_key_wraps', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('container', 'user')},
            },
        ),
        migrations.RunPython(
            migrate_team_credentials_into_containers,
            reverse_migrate_team_credentials_into_containers,
        ),
    ]
