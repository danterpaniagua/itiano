from django.contrib.auth.models import User
from django.db import models


class ClipboardEntry(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='clipboard')
    content = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Clipboard({self.user})"

    def get_decrypted(self) -> str:
        from .crypto import decrypt
        return decrypt(self.content)

    def set_content(self, plaintext: str):
        from .crypto import encrypt
        self.content = encrypt(plaintext)
