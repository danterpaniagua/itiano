from django.contrib.auth.models import User
from django.db import models


class Notebook(models.Model):
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notebooks')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        unique_together = [('owner', 'name')]

    def __str__(self):
        return self.name


class Note(models.Model):
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    notebook = models.ForeignKey(
        Notebook, on_delete=models.SET_NULL, null=True, blank=True, related_name='notes'
    )
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_notes')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.title


class NoteShare(models.Model):
    PERM_READ = 'read'
    PERM_WRITE = 'write'
    PERMISSIONS = [
        (PERM_READ, 'Read'),
        (PERM_WRITE, 'Write'),
    ]

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name='shares')
    shared_with = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shared_notes')
    permission = models.CharField(max_length=10, choices=PERMISSIONS, default=PERM_READ)

    class Meta:
        unique_together = [('note', 'shared_with')]
