import base64
import hashlib
import hmac
import os
import secrets

from cryptography.fernet import Fernet
from django.conf import settings


def _derive_wrapping_key(salt: str) -> Fernet:
    """Derive wrapping key using PBKDF2-HMAC-SHA256 with a per-user salt."""
    raw = hashlib.pbkdf2_hmac(
        'sha256',
        settings.SECRET_KEY.encode(),
        salt.encode(),
        iterations=260_000,
    )
    return Fernet(base64.urlsafe_b64encode(raw))


def _legacy_app_fernet() -> Fernet:
    """Legacy SHA-256 derivation for keys created before v5.8.17."""
    raw = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def get_user_fernet(user):
    from .models import UserVaultKey
    record, created = UserVaultKey.objects.get_or_create(user=user)
    if created:
        salt = secrets.token_hex(32)
        key = Fernet.generate_key()
        record.salt = salt
        record.encrypted_key = _derive_wrapping_key(salt).encrypt(key).decode()
        record.save()
    else:
        if record.salt:
            key = _derive_wrapping_key(record.salt).decrypt(record.encrypted_key.encode())
        else:
            # Legacy key: wrapped with SHA-256 derivation (no salt)
            key = _legacy_app_fernet().decrypt(record.encrypted_key.encode())
    return Fernet(key)


def encrypt_for_user(user, plaintext: str) -> str:
    if not plaintext:
        return ''
    return get_user_fernet(user).encrypt(plaintext.encode()).decode()


def decrypt_for_user(user, token: str) -> str:
    if not token:
        return ''
    return get_user_fernet(user).decrypt(token.encode()).decode()


def provision_team_key(team):
    """Create the team's Fernet data-key and wrap it for every current member.

    Lazy — only called the first time a team credential is encrypted and the
    team has no TeamKeyWrap rows yet.
    """
    from .models import TeamKeyWrap
    key = Fernet.generate_key()
    for member in team.members.all():
        wrapped = get_user_fernet(member).encrypt(key).decode()
        TeamKeyWrap.objects.update_or_create(
            team=team, user=member, defaults={'wrapped_key': wrapped},
        )


def wrap_team_key_for_user(team, user):
    """Wrap the team's existing key for a member who doesn't have a wrap yet.

    Requires the team to already have at least one wrap (i.e. a key exists) —
    unwraps it via any existing member, then re-wraps it for `user`.
    """
    from .models import TeamKeyWrap
    existing = TeamKeyWrap.objects.filter(team=team).exclude(user=user).first()
    if existing is None:
        # No key provisioned yet — nothing to wrap for this user (or they're
        # the only member); provisioning will pick them up when it runs.
        return
    key = get_user_fernet(existing.user).decrypt(existing.wrapped_key.encode())
    wrapped = get_user_fernet(user).encrypt(key).decode()
    TeamKeyWrap.objects.update_or_create(
        team=team, user=user, defaults={'wrapped_key': wrapped},
    )


def get_team_fernet(team, acting_user) -> Fernet:
    from django.core.exceptions import PermissionDenied
    from .models import TeamKeyWrap

    wrap = TeamKeyWrap.objects.filter(team=team, user=acting_user).first()
    if wrap is None:
        if not TeamKeyWrap.objects.filter(team=team).exists():
            provision_team_key(team)
            wrap = TeamKeyWrap.objects.filter(team=team, user=acting_user).first()
        if wrap is None:
            raise PermissionDenied(f"{acting_user} has no key wrap for team {team}")
    key = get_user_fernet(acting_user).decrypt(wrap.wrapped_key.encode())
    return Fernet(key)


def encrypt_for_team(team, acting_user, plaintext: str) -> str:
    if not plaintext:
        return ''
    return get_team_fernet(team, acting_user).encrypt(plaintext.encode()).decode()


def decrypt_for_team(team, acting_user, token: str) -> str:
    if not token:
        return ''
    return get_team_fernet(team, acting_user).decrypt(token.encode()).decode()


def rotate_team_key(team, excluded_users=None):
    """Rotate the team's key: re-encrypt all its credentials' secret fields
    with a fresh key, then re-wrap that key for current members minus
    `excluded_users` (an iterable of User, used when member(s) are being
    removed — pass all of them in one call to avoid redundant rotations).
    """
    from .models import TeamKeyWrap, Credential

    excluded_ids = {u.pk for u in excluded_users} if excluded_users else set()
    old_wrap = TeamKeyWrap.objects.filter(team=team).exclude(user_id__in=excluded_ids).first()
    secret_fields = ['encrypted_password', 'encrypted_private_key', 'encrypted_passphrase']

    if old_wrap is not None:
        old_fernet = Fernet(get_user_fernet(old_wrap.user).decrypt(old_wrap.wrapped_key.encode()))
        new_key = Fernet.generate_key()
        new_fernet = Fernet(new_key)

        for credential in Credential.objects.filter(team=team, visibility=Credential.VIS_TEAM):
            updates = {}
            for field in secret_fields:
                token = getattr(credential, field)
                if token:
                    plaintext = old_fernet.decrypt(token.encode())
                    updates[field] = new_fernet.encrypt(plaintext).decode()
            if updates:
                Credential.objects.filter(pk=credential.pk).update(**updates)
    else:
        # No existing key to rotate from (team had no wraps at all) — just
        # generate one fresh; there's nothing to re-encrypt.
        new_key = Fernet.generate_key()

    TeamKeyWrap.objects.filter(team=team).delete()
    remaining = team.members.exclude(pk__in=excluded_ids) if excluded_ids else team.members.all()
    for member in remaining:
        wrapped = get_user_fernet(member).encrypt(new_key).decode()
        TeamKeyWrap.objects.create(team=team, user=member, wrapped_key=wrapped)


def get_container_members(container):
    """Union of every team's members across all ContainerAccess grants (any
    level) on this container, plus the container's creator.
    """
    from django.contrib.auth.models import User
    from .models import ContainerAccess

    team_ids = ContainerAccess.objects.filter(container=container).values_list('team_id', flat=True)
    qs = User.objects.filter(vault_teams__id__in=team_ids)
    if container.created_by_id:
        qs = qs | User.objects.filter(pk=container.created_by_id)
    return qs.distinct()


def provision_container_key(container):
    """Create the container's Fernet data-key and wrap it for every current
    member (lazy — called the first time a container credential is
    encrypted and the container has no ContainerKeyWrap rows yet).
    """
    from .models import ContainerKeyWrap
    key = Fernet.generate_key()
    for member in get_container_members(container):
        wrapped = get_user_fernet(member).encrypt(key).decode()
        ContainerKeyWrap.objects.update_or_create(
            container=container, user=member, defaults={'wrapped_key': wrapped},
        )


def wrap_container_key_for_user(container, user):
    """Wrap the container's existing key for a member who doesn't have a
    wrap yet. Requires the container to already have at least one wrap.
    """
    from .models import ContainerKeyWrap
    existing = ContainerKeyWrap.objects.filter(container=container).exclude(user=user).first()
    if existing is None:
        return
    key = get_user_fernet(existing.user).decrypt(existing.wrapped_key.encode())
    wrapped = get_user_fernet(user).encrypt(key).decode()
    ContainerKeyWrap.objects.update_or_create(
        container=container, user=user, defaults={'wrapped_key': wrapped},
    )


def get_container_fernet(container, acting_user) -> Fernet:
    from django.core.exceptions import PermissionDenied
    from .models import ContainerKeyWrap

    wrap = ContainerKeyWrap.objects.filter(container=container, user=acting_user).first()
    if wrap is None:
        if not ContainerKeyWrap.objects.filter(container=container).exists():
            provision_container_key(container)
            wrap = ContainerKeyWrap.objects.filter(container=container, user=acting_user).first()
        if wrap is None:
            raise PermissionDenied(f"{acting_user} has no key wrap for container {container}")
    key = get_user_fernet(acting_user).decrypt(wrap.wrapped_key.encode())
    return Fernet(key)


def encrypt_for_container(container, acting_user, plaintext: str) -> str:
    if not plaintext:
        return ''
    return get_container_fernet(container, acting_user).encrypt(plaintext.encode()).decode()


def decrypt_for_container(container, acting_user, token: str) -> str:
    if not token:
        return ''
    return get_container_fernet(container, acting_user).decrypt(token.encode()).decode()


def rotate_container_key(container, excluded_users=None):
    """Rotate the container's key: re-encrypt all its credentials' secret
    fields with a fresh key, then re-wrap for current members minus
    `excluded_users`.
    """
    from .models import ContainerKeyWrap, Credential

    excluded_ids = {u.pk for u in excluded_users} if excluded_users else set()
    old_wrap = ContainerKeyWrap.objects.filter(container=container).exclude(user_id__in=excluded_ids).first()
    secret_fields = ['encrypted_password', 'encrypted_private_key', 'encrypted_passphrase']

    if old_wrap is not None:
        old_fernet = Fernet(get_user_fernet(old_wrap.user).decrypt(old_wrap.wrapped_key.encode()))
        new_key = Fernet.generate_key()
        new_fernet = Fernet(new_key)

        for credential in Credential.objects.filter(container=container):
            updates = {}
            for field in secret_fields:
                token = getattr(credential, field)
                if token:
                    plaintext = old_fernet.decrypt(token.encode())
                    updates[field] = new_fernet.encrypt(plaintext).decode()
            if updates:
                Credential.objects.filter(pk=credential.pk).update(**updates)
    else:
        new_key = Fernet.generate_key()

    ContainerKeyWrap.objects.filter(container=container).delete()
    remaining = get_container_members(container).exclude(pk__in=excluded_ids)
    for member in remaining:
        wrapped = get_user_fernet(member).encrypt(new_key).decode()
        ContainerKeyWrap.objects.create(container=container, user=member, wrapped_key=wrapped)


def reconcile_container_access(container):
    """Bring ContainerKeyWrap in sync with current valid membership
    (get_container_members) — the single source of truth for "who should
    be able to decrypt this container right now."

    Deliberately recomputes from scratch rather than tracking who-was-
    added/removed via signal payloads: m2m_changed does NOT fire when M2M
    rows are cleared as a side effect of cascade-deleting a related object
    (e.g. Team.delete() does not trigger pre_remove/post_clear on
    Team.members), so any logic that reasons about "the users just removed"
    from a signal's own payload is unreliable during cascades. Reconciling
    against current ground truth sidesteps that entirely — safe to call
    from any trigger, any number of times, no-op if already in sync.
    """
    from .models import ContainerKeyWrap
    from django.contrib.auth.models import User

    valid_ids = set(get_container_members(container).values_list('pk', flat=True))
    wrapped_ids = set(ContainerKeyWrap.objects.filter(container=container).values_list('user_id', flat=True))

    stale_ids = wrapped_ids - valid_ids
    if stale_ids:
        rotate_container_key(container, excluded_users=list(User.objects.filter(pk__in=stale_ids)))
        wrapped_ids = valid_ids  # rotation just wrapped every currently-valid member

    missing_ids = valid_ids - wrapped_ids
    if missing_ids and ContainerKeyWrap.objects.filter(container=container).exists():
        for user in User.objects.filter(pk__in=missing_ids):
            wrap_container_key_for_user(container, user)


def _resolve_credential_boundary(credential):
    """How a credential's SECRET fields are actually encrypted: container
    beats legacy team beats personal. Must match credential_copy/CredentialForm
    exactly — this is the single source of truth both defer to.
    """
    from .models import Credential
    if credential.container_id:
        return ('container', credential.container)
    if credential.visibility == Credential.VIS_TEAM and credential.team_id:
        return ('team', credential.team)
    return ('personal', credential.owner)


def encrypt_for_credential(credential, acting_user, plaintext: str) -> str:
    kind, target = _resolve_credential_boundary(credential)
    if kind == 'container':
        return encrypt_for_container(target, acting_user, plaintext)
    if kind == 'team':
        return encrypt_for_team(target, acting_user, plaintext)
    return encrypt_for_user(target, plaintext)


def decrypt_for_credential(credential, acting_user, token: str) -> str:
    kind, target = _resolve_credential_boundary(credential)
    if kind == 'container':
        return decrypt_for_container(target, acting_user, token)
    if kind == 'team':
        return decrypt_for_team(target, acting_user, token)
    return decrypt_for_user(target, token)


def encrypt_notes_for_credential(credential, acting_user, plaintext: str) -> str:
    """Notes have their own independent sharing boundary (notes_shared),
    separate from _resolve_credential_boundary — sharing the secret must
    never imply sharing notes. Only the container path is ever shared;
    a legacy team credential's notes_shared has no observable effect (see
    v5.10.3.md known limitation) — not worth a third encryption path.
    """
    if credential.notes_shared and credential.container_id:
        return encrypt_for_container(credential.container, acting_user, plaintext)
    return encrypt_for_user(credential.owner, plaintext)


def decrypt_notes_for_credential(credential, acting_user, token: str) -> str:
    if credential.notes_shared and credential.container_id:
        return decrypt_for_container(credential.container, acting_user, token)
    return decrypt_for_user(credential.owner, token)
