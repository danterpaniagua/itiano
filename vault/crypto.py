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
