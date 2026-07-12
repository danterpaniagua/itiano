from django.contrib.auth.models import User
from django.db import models


class TeamKeyWrap(models.Model):
    team = models.ForeignKey('core.Team', on_delete=models.CASCADE, related_name='key_wraps')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='team_key_wraps')
    wrapped_key = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('team', 'user')]

    def __str__(self):
        return f"TeamKeyWrap({self.team}, {self.user})"


class Container(models.Model):
    name = models.CharField(max_length=200)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ContainerAccess(models.Model):
    ACCESS_READ = 'read'
    ACCESS_READ_WRITE = 'read_write'
    ACCESS_LEVELS = [
        (ACCESS_READ, 'Read'),
        (ACCESS_READ_WRITE, 'Read/Write'),
    ]

    container = models.ForeignKey(Container, on_delete=models.CASCADE, related_name='access_grants')
    team = models.ForeignKey('core.Team', on_delete=models.CASCADE, related_name='container_access_grants')
    access_level = models.CharField(max_length=10, choices=ACCESS_LEVELS, default=ACCESS_READ)

    class Meta:
        unique_together = [('container', 'team')]

    def __str__(self):
        return f"{self.team} → {self.container} ({self.access_level})"


class ContainerKeyWrap(models.Model):
    container = models.ForeignKey(Container, on_delete=models.CASCADE, related_name='key_wraps')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='container_key_wraps')
    wrapped_key = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('container', 'user')]

    def __str__(self):
        return f"ContainerKeyWrap({self.container}, {self.user})"


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
    team = models.ForeignKey('core.Team', on_delete=models.SET_NULL, null=True, blank=True, related_name='credentials')
    # Legacy team-sharing fields (team/visibility) are kept as-is — not repurposed or
    # removed — until the tree UI (v5.10.3) fully replaces them as the navigation model.
    container = models.ForeignKey('Container', on_delete=models.PROTECT, null=True, blank=True, related_name='credentials')
    visibility = models.CharField(max_length=10, choices=VISIBILITIES, default=VIS_PERSONAL)
    credential_type = models.CharField(max_length=20, choices=TYPES)
    name = models.CharField(max_length=200)
    # Notes are encrypted independently from the secret fields, with their own
    # sharing toggle — sharing a credential's password must never imply
    # sharing its notes. Default (notes_shared=False) always uses the
    # owner's personal key, regardless of how the secret itself is shared.
    encrypted_notes = models.TextField(blank=True)
    notes_shared = models.BooleanField(default=False)
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

    is_deleted = models.BooleanField(default=False)

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
    public_key = models.TextField(blank=True)
    certificate_pem = models.TextField(blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)
    notes_shared = models.BooleanField(default=False)

    # Encrypted snapshot (ciphertext stored as-is)
    encrypted_password = models.TextField(blank=True)
    encrypted_private_key = models.TextField(blank=True)
    encrypted_passphrase = models.TextField(blank=True)
    encrypted_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-version_number']
        unique_together = [('credential', 'version_number')]

    def __str__(self):
        return f"{self.credential} v{self.version_number}"
