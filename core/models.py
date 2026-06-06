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

    def __str__(self):
        return f"{self.user.username} ({self.role})"
