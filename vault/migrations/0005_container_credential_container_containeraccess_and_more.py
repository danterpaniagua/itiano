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
    """
    from vault.crypto import decrypt_for_team, encrypt_for_container
    from vault.models import Container, ContainerAccess, Credential, Team

    secret_fields = ['encrypted_password', 'encrypted_private_key', 'encrypted_passphrase']

    for team in Team.objects.all():
        team_credentials = Credential.objects.filter(team=team, visibility=Credential.VIS_TEAM)
        if not team_credentials.exists():
            continue

        container = Container.objects.create(name=team.name, created_by=None)
        ContainerAccess.objects.create(
            container=container, team=team, access_level=ContainerAccess.ACCESS_READ_WRITE,
        )

        for credential in team_credentials:
            try:
                updates = {'container_id': container.pk}
                for field in secret_fields:
                    token = getattr(credential, field)
                    if token:
                        plaintext = decrypt_for_team(team, credential.owner, token)
                        updates[field] = encrypt_for_container(container, credential.owner, plaintext)
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
