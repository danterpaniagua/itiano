from django.contrib.auth.models import User
from django.db import models


class Team(models.Model):
    name = models.CharField(max_length=100, unique=True)
    members = models.ManyToManyField(User, blank=True, related_name='vault_teams')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class UserVaultKey(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='vault_key')
    encrypted_key = models.TextField()
    # salt is None for keys created before v5.8.17 (legacy SHA-256 derivation).
    # New keys use PBKDF2-HMAC-SHA256 with this random salt.
    salt = models.CharField(max_length=64, blank=True, default='')

    def __str__(self):
        return f"VaultKey({self.user})"


class Tag(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Credential(models.Model):
    TYPE_PASSWORD = 'password'
    TYPE_SSH_KEY = 'ssh_key'
    TYPE_CERTIFICATE = 'certificate'
    TYPES = [
        (TYPE_PASSWORD, 'Password'),
        (TYPE_SSH_KEY, 'SSH Key'),
        (TYPE_CERTIFICATE, 'Certificate'),
    ]

    VIS_PERSONAL = 'personal'
    VIS_TEAM = 'team'
    VISIBILITIES = [
        (VIS_PERSONAL, 'Personal'),
        (VIS_TEAM, 'Team'),
    ]

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='credentials')
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='credentials')
    visibility = models.CharField(max_length=10, choices=VISIBILITIES, default=VIS_PERSONAL)
    credential_type = models.CharField(max_length=20, choices=TYPES)
    name = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name='credentials')
    expiry_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Password fields
    url = models.CharField(max_length=500, blank=True)
    username = models.CharField(max_length=200, blank=True)
    encrypted_password = models.TextField(blank=True)

    # SSH key / Certificate fields
    encrypted_private_key = models.TextField(blank=True)
    public_key = models.TextField(blank=True)
    encrypted_passphrase = models.TextField(blank=True)

    # Certificate fields
    certificate_pem = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def is_expiring_soon(self):
        if not self.expiry_date:
            return False
        from django.utils import timezone
        return (self.expiry_date - timezone.now().date()).days <= 30


class CredentialVersion(models.Model):
    credential = models.ForeignKey(Credential, on_delete=models.CASCADE, related_name='versions')
    version_number = models.PositiveIntegerField()
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    changed_fields = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Plaintext snapshot
    name = models.CharField(max_length=200, blank=True)
    credential_type = models.CharField(max_length=20, blank=True)
    visibility = models.CharField(max_length=10, blank=True)
    url = models.CharField(max_length=500, blank=True)
    username = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    public_key = models.TextField(blank=True)
    certificate_pem = models.TextField(blank=True)
    expiry_date = models.DateField(null=True, blank=True)

    # Encrypted snapshot (ciphertext stored as-is)
    encrypted_password = models.TextField(blank=True)
    encrypted_private_key = models.TextField(blank=True)
    encrypted_passphrase = models.TextField(blank=True)

    class Meta:
        ordering = ['-version_number']
        unique_together = [('credential', 'version_number')]

    def __str__(self):
        return f"{self.credential} v{self.version_number}"
