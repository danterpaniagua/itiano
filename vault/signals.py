from django.db.models.signals import post_save, m2m_changed
from django.dispatch import receiver

_PLAINTEXT_FIELDS = ['name', 'credential_type', 'visibility', 'url', 'username',
                     'notes', 'public_key', 'certificate_pem', 'expiry_date']
_SECRET_LABELS = {
    'encrypted_password': 'password changed',
    'encrypted_private_key': 'private key changed',
    'encrypted_passphrase': 'passphrase changed',
}


@receiver(post_save, sender='vault.Credential')
def create_version(sender, instance, created, **kwargs):
    from .models import CredentialVersion

    last = instance.versions.first()
    version_number = (last.version_number + 1) if last else 1

    changed = []
    if last:
        for field in _PLAINTEXT_FIELDS:
            if str(getattr(instance, field, '') or '') != str(getattr(last, field, '') or ''):
                changed.append(field.replace('_', ' '))
        for enc_field, label in _SECRET_LABELS.items():
            if getattr(instance, enc_field, '') != getattr(last, enc_field, ''):
                changed.append(label)
    else:
        changed.append('created')

    CredentialVersion.objects.create(
        credential=instance,
        version_number=version_number,
        changed_by=getattr(instance, '_changed_by', None),
        changed_fields=', '.join(changed),
        name=instance.name,
        credential_type=instance.credential_type,
        visibility=instance.visibility,
        url=instance.url,
        username=instance.username,
        notes=instance.notes,
        public_key=instance.public_key,
        certificate_pem=instance.certificate_pem,
        expiry_date=instance.expiry_date,
        encrypted_password=instance.encrypted_password,
        encrypted_private_key=instance.encrypted_private_key,
        encrypted_passphrase=instance.encrypted_passphrase,
    )


@receiver(m2m_changed, sender='vault.Team_members')
def handle_team_membership_change(sender, instance, action, pk_set, **kwargs):
    from django.contrib.auth.models import User
    from .crypto import wrap_team_key_for_user, rotate_team_key
    from .models import TeamKeyWrap

    if action == 'post_add':
        if TeamKeyWrap.objects.filter(team=instance).exists():
            for user in User.objects.filter(pk__in=pk_set):
                wrap_team_key_for_user(instance, user)
    elif action == 'pre_remove':
        removed_users = list(User.objects.filter(pk__in=pk_set))
        if removed_users:
            rotate_team_key(instance, excluded_users=removed_users)
    # 'pre_clear'/'post_clear' (removing all members at once) intentionally
    # unhandled — see v5.10.0.md Out of Scope. Rotating-to-zero-members here
    # would orphan the just-rotated ciphertext the next time it's accessed
    # (provisioning would silently generate yet another key), which is worse
    # than doing nothing. Existing wraps are left in place until a real
    # design for this edge case is scoped.
