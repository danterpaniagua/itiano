from django.contrib import admin

from .models import Credential, Tag, UserVaultKey


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']


@admin.register(Credential)
class CredentialAdmin(admin.ModelAdmin):
    list_display = ['name', 'credential_type', 'visibility', 'owner', 'team', 'expiry_date', 'is_deleted']
    list_filter = ['credential_type', 'visibility', 'is_deleted']
    search_fields = ['name', 'username', 'url']
    readonly_fields = ['encrypted_password', 'encrypted_private_key', 'encrypted_passphrase']


@admin.register(UserVaultKey)
class UserVaultKeyAdmin(admin.ModelAdmin):
    list_display = ['user']
    readonly_fields = ['encrypted_key']
