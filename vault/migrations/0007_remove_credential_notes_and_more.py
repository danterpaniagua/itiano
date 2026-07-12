from django.db import migrations, models


def encrypt_existing_notes(apps, schema_editor):
    """Move plaintext notes to encrypted_notes before the old column is
    dropped. notes_shared defaults to False, so the owner's personal key is
    the correct boundary for every existing row (v5.10.3).

    Uses apps.get_model (historical migration-state models, which still
    have BOTH `notes` and `encrypted_notes` at this point in the graph) for
    the query, not the live vault.models import — models.py has already
    been edited to drop `notes` entirely by the time this migration runs.
    encrypt_for_user itself is fine to import live; it doesn't depend on
    Credential's field set — but it does require a *live* User instance
    (UserVaultKey.user is a live FK), not the historical one apps.get_model
    hands back, so owners are re-fetched live by pk below.
    """
    from django.contrib.auth.models import User
    from vault.crypto import encrypt_for_user
    Credential = apps.get_model('vault', 'Credential')
    CredentialVersion = apps.get_model('vault', 'CredentialVersion')

    for credential in Credential.objects.exclude(notes=''):
        owner = User.objects.get(pk=credential.owner_id)
        Credential.objects.filter(pk=credential.pk).update(
            encrypted_notes=encrypt_for_user(owner, credential.notes)
        )

    for version in CredentialVersion.objects.exclude(notes='').select_related('credential'):
        # Historical versions don't track a per-version owner — use the
        # credential's current owner (owner is never reassigned after
        # creation, see feature_vault.md).
        owner = User.objects.get(pk=version.credential.owner_id)
        CredentialVersion.objects.filter(pk=version.pk).update(
            encrypted_notes=encrypt_for_user(owner, version.notes)
        )


def reverse_encrypt_existing_notes(apps, schema_editor):
    raise migrations.exceptions.IrreversibleError(
        'Cannot reverse notes encryption: the plaintext notes column will '
        'already be dropped by the time this would run. Restore from a '
        'backup taken before this migration instead.'
    )


class Migration(migrations.Migration):

    dependencies = [
        ('vault', '0006_credential_is_deleted_credentialversion_is_deleted'),
    ]

    operations = [
        migrations.AddField(
            model_name='credential',
            name='encrypted_notes',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='credential',
            name='notes_shared',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='credentialversion',
            name='encrypted_notes',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='credentialversion',
            name='notes_shared',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(encrypt_existing_notes, reverse_encrypt_existing_notes),
        migrations.RemoveField(
            model_name='credential',
            name='notes',
        ),
        migrations.RemoveField(
            model_name='credentialversion',
            name='notes',
        ),
    ]
