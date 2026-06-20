import hashlib

from django.contrib.auth.models import User
from django.db import models


class UserProfile(models.Model):
    ROLES = [
        ('requester', 'Requester'),
        ('agent', 'Agent'),
        ('manager', 'Manager'),
        ('admin', 'Admin'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='userprofile')
    role = models.CharField(max_length=20, choices=ROLES, default='requester')
    jira_account_id = models.CharField(max_length=100, blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} ({self.role})"

    def avatar_url(self):
        if self.avatar:
            return self.avatar.url
        email = (self.user.email or '').strip().lower()
        h = hashlib.md5(email.encode()).hexdigest()
        return f"https://www.gravatar.com/avatar/{h}?s=80&d=identicon"
