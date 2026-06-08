import base64
import hashlib
import os

from cryptography.fernet import Fernet
from django.conf import settings


def _app_fernet():
    raw = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def get_user_fernet(user):
    from .models import UserVaultKey
    record, created = UserVaultKey.objects.get_or_create(user=user)
    if created:
        key = Fernet.generate_key()
        record.encrypted_key = _app_fernet().encrypt(key).decode()
        record.save()
    else:
        key = _app_fernet().decrypt(record.encrypted_key.encode())
    return Fernet(key)


def encrypt_for_user(user, plaintext: str) -> str:
    if not plaintext:
        return ''
    return get_user_fernet(user).encrypt(plaintext.encode()).decode()


def decrypt_for_user(user, token: str) -> str:
    if not token:
        return ''
    return get_user_fernet(user).decrypt(token.encode()).decode()
