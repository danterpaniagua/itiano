import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils.text import slugify


def backfill_team_codes(apps, schema_editor):
    Team = apps.get_model('vault', 'Team')
    seen = set(Team.objects.exclude(code='').values_list('code', flat=True))
    for team in Team.objects.filter(code=''):
        base = slugify(team.name) or 'team'
        code = base
        suffix = 2
        while code in seen:
            code = f'{base}-{suffix}'
            suffix += 1
        seen.add(code)
        team.code = code
        team.save(update_fields=['code'])


def reverse_backfill_team_codes(apps, schema_editor):
    # No-op — codes are cosmetic identifiers, nothing depends on reverting them.
    pass


def reencrypt_team_credentials(apps, schema_editor):
    """One-time move of existing visibility='team' credential secrets from
    owner-key encryption to team-key encryption (v5.10.0). Uses the real
    vault.crypto helpers for the actual Fernet/key-wrapping logic (not
    something a migration should reimplement), but queries via apps.get_model
    (historical state) and re-fetches owners as live User instances by pk —
    crypto.py's get_user_fernet requires a live User, not the historical
    apps.get_model version (see v5.10.3.md Delivery Note for the same
    lesson learned later). Fixed retroactively in v5.10.4 when Team moved
    to core — this function's original live `from vault.models import Team`
    stopped resolving once Team left vault.models, exposing that it had
    always needed apps.get_model for a correct from-scratch migration replay.
    """
    from django.contrib.auth.models import User
    from core.models import Team as LiveTeam
    from vault.crypto import decrypt_for_user, encrypt_for_team
    Credential = apps.get_model('vault', 'Credential')
    Team = apps.get_model('vault', 'Team')

    secret_fields = ['encrypted_password', 'encrypted_private_key', 'encrypted_passphrase']

    for team in Team.objects.all():
        # encrypt_for_team queries the live TeamKeyWrap model, whose `team`
        # FK now points to core.Team (post-v5.10.4) — needs a live-typed
        # instance, not this historical one, same reasoning as `owner` below.
        # The underlying vault_team table/row is identical either way (this
        # migration makes no schema change to Team), so this is safe
        # regardless of core's Team migration's relative ordering.
        live_team = LiveTeam.objects.get(pk=team.pk)
        for credential in Credential.objects.filter(team=team, visibility='team'):
            owner = User.objects.get(pk=credential.owner_id)
            updates = {}
            for field in secret_fields:
                token = getattr(credential, field)
                if token:
                    plaintext = decrypt_for_user(owner, token)
                    updates[field] = encrypt_for_team(live_team, owner, plaintext)
            if updates:
                Credential.objects.filter(pk=credential.pk).update(**updates)


def reverse_reencrypt_team_credentials(apps, schema_editor):
    raise migrations.exceptions.IrreversibleError(
        'Cannot reverse team-key re-encryption: the team key that would be '
        'needed to decrypt back to owner-key encryption is only recoverable '
        'through TeamKeyWrap rows, which a schema-level reversal would drop '
        'first. Restore from a backup taken before this migration instead.'
    )


class Migration(migrations.Migration):

    dependencies = [
        ('vault', '0003_uservaultkey_salt'),
        # Added in v5.10.4: reencrypt_team_credentials (below) now needs a
        # live core.models.Team for encrypt_for_team — not strictly required
        # at the DB level (vault_team's physical table never changes across
        # this whole migration sequence), but makes the real runtime
        # dependency explicit and guarantees deterministic ordering on a
        # fresh replay.
        ('core', '0004_team'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='team',
            name='code',
            # db_index=False here on purpose: SlugField defaults to
            # db_index=True, which queues a *deferred* index-creation SQL
            # statement that only flushes at the end of this migration's
            # transaction. The later AlterField(unique=True) below creates
            # its own same-named index immediately, so the deferred one from
            # this step would collide with it ("already exists") when
            # flushed. The final AlterField's unique constraint provides the
            # index anyway, so no indexing is needed at this intermediate step.
            field=models.SlugField(blank=True, default='', max_length=50, db_index=False),
        ),
        migrations.AddField(
            model_name='team',
            name='description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.CreateModel(
            name='TeamKeyWrap',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('wrapped_key', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('team', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='key_wraps', to='vault.team')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='team_key_wraps', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('team', 'user')},
            },
        ),
        migrations.RunPython(backfill_team_codes, reverse_backfill_team_codes),
        migrations.AlterField(
            model_name='team',
            name='code',
            field=models.SlugField(blank=True, max_length=50, unique=True),
        ),
        migrations.RunPython(reencrypt_team_credentials, reverse_reencrypt_team_credentials),
    ]
