import hashlib

from django.contrib.auth.models import User
from django.db import models
from django.utils.text import slugify


class Team(models.Model):
    """App-wide team/group concept. Currently only consumed by the vault
    app (TeamKeyWrap, ContainerAccess, Credential.team), but lives here so
    other apps can use it later without a repeat of this relocation.

    db_table is pinned to the original vault_team/vault_team_members names
    deliberately — this move is state-only (see .claude/v5.10.4.md), no
    physical table rename, to minimize risk to the already-shipped vault
    crypto foundation these tables underpin.
    """
    name = models.CharField(max_length=100, unique=True)
    code = models.SlugField(max_length=50, unique=True, blank=True)
    description = models.TextField(blank=True, default='')
    members = models.ManyToManyField(User, blank=True, related_name='vault_teams', db_table='vault_team_members')

    class Meta:
        ordering = ['name']
        db_table = 'vault_team'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.code:
            base = slugify(self.name) or 'team'
            code = base
            suffix = 2
            while Team.objects.exclude(pk=self.pk).filter(code=code).exists():
                code = f'{base}-{suffix}'
                suffix += 1
            self.code = code
        super().save(*args, **kwargs)


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
