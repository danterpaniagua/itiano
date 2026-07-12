from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver

_PLAINTEXT_FIELDS = ['name', 'credential_type', 'visibility', 'url', 'username',
                     'public_key', 'certificate_pem', 'expiry_date']
_SECRET_LABELS = {
    'encrypted_password': 'password changed',
    'encrypted_private_key': 'private key changed',
    'encrypted_passphrase': 'passphrase changed',
    'encrypted_notes': 'notes changed',
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
        if bool(last.is_deleted) != bool(instance.is_deleted):
            changed.append('deleted' if instance.is_deleted else 'restored')
        if bool(last.notes_shared) != bool(instance.notes_shared):
            changed.append('notes shared' if instance.notes_shared else 'notes unshared')
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
        public_key=instance.public_key,
        certificate_pem=instance.certificate_pem,
        expiry_date=instance.expiry_date,
        is_deleted=instance.is_deleted,
        notes_shared=instance.notes_shared,
        encrypted_password=instance.encrypted_password,
        encrypted_private_key=instance.encrypted_private_key,
        encrypted_passphrase=instance.encrypted_passphrase,
        encrypted_notes=instance.encrypted_notes,
    )


@receiver(m2m_changed, sender='core.Team_members')
def handle_team_membership_change(sender, instance, action, pk_set, **kwargs):
    from django.contrib.auth.models import User
    from .crypto import wrap_team_key_for_user, rotate_team_key, reconcile_container_access
    from .models import TeamKeyWrap, ContainerAccess

    if action == 'post_add':
        added_users = list(User.objects.filter(pk__in=pk_set))
        if TeamKeyWrap.objects.filter(team=instance).exists():
            for user in added_users:
                wrap_team_key_for_user(instance, user)
    elif action == 'pre_remove':
        removed_users = list(User.objects.filter(pk__in=pk_set))
        if removed_users:
            rotate_team_key(instance, excluded_users=removed_users)
    # Containers this team has access to: reconcile against current ground
    # truth (see reconcile_container_access docstring) rather than pk_set.
    # Must run on post_add / post_remove specifically — pre_remove fires
    # BEFORE the membership row is actually gone, so a ground-truth query
    # at that point would still see the about-to-be-removed user as valid.
    # rotate_team_key above doesn't have this problem because it takes an
    # explicit exclusion list instead of re-querying membership.
    if action in ('post_add', 'post_remove'):
        for grant in ContainerAccess.objects.filter(team=instance).select_related('container'):
            reconcile_container_access(grant.container)
    # 'pre_clear'/'post_clear' (removing all members at once) intentionally
    # unhandled for TeamKeyWrap — see v5.10.0.md Out of Scope. Rotating-to-
    # zero-members here would orphan the just-rotated ciphertext the next
    # time it's accessed (provisioning would silently generate yet another
    # key), which is worse than doing nothing.


@receiver(post_save, sender='vault.ContainerAccess')
def handle_container_access_created(sender, instance, created, **kwargs):
    if not created:
        return
    from .crypto import reconcile_container_access
    reconcile_container_access(instance.container)


@receiver(post_delete, sender='vault.ContainerAccess')
def handle_container_access_deleted(sender, instance, **kwargs):
    from .crypto import reconcile_container_access
    reconcile_container_access(instance.container)
