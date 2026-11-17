from django.contrib.auth.models import User
from django.db import IntegrityError, models


class Notebook(models.Model):
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notebooks')
    created_at = models.DateTimeField(auto_now_add=True)
    # System folders (v5.19.0): snake_case id, nested under a parent, global (see notes/system_prompts.py).
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    key = models.CharField(max_length=64, blank=True, default='')
    is_system = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']
        constraints = [
            # MongoDB unique indexes ignore null values, so this index only covers nested folders;
            # root-level (parent is null) uniqueness is enforced in save().
            models.UniqueConstraint(
                fields=['owner', 'parent', 'name'], condition=models.Q(is_system=False),
                name='notes_notebook_owner_parent_name_uniq',
            ),
            models.UniqueConstraint(
                fields=['key'], condition=models.Q(key__gt=''), name='notes_notebook_key_uniq',
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.parent_id is None and not self.is_system and Notebook.objects.exclude(pk=self.pk).filter(
            owner_id=self.owner_id, name=self.name, parent__isnull=True, is_system=False,
        ).exists():
            raise IntegrityError('Duplicate personal notebook name for this owner.')
        super().save(*args, **kwargs)


class Note(models.Model):
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    notebook = models.ForeignKey(
        Notebook, on_delete=models.SET_NULL, null=True, blank=True, related_name='notes'
    )
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_notes')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_system = models.BooleanField(default=False)
    # System prompt id (`prompt_<feature>`, v5.19.0); empty for personal notes.
    key = models.CharField(max_length=100, blank=True, default='')
    # Id of a generated personal file inside its notebook (v5.22.0), e.g. `2026-11` or `2026-11_W45`.
    file_id = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        ordering = ['-updated_at']
        permissions = [('view_system_prompts', 'Can view system prompts')]
        constraints = [
            models.UniqueConstraint(fields=['key'], condition=models.Q(key__gt=''), name='notes_note_key_uniq'),
            models.UniqueConstraint(
                fields=['notebook', 'file_id'], condition=models.Q(file_id__gt=''),
                name='notes_note_file_id_per_notebook_uniq',
            ),
        ]

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


class NoteMention(models.Model):
    """Objects a note mentions with `@` (v5.18.7). Rebuilt from the body on every save."""
    KIND_JIRA = 'jira'
    KIND_TICKET = 'ticket'
    KIND_CRED = 'cred'
    KINDS = [
        (KIND_JIRA, 'Jira ticket'),
        (KIND_TICKET, 'ITSM ticket'),
        (KIND_CRED, 'Credential'),
    ]

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name='mentions')
    kind = models.CharField(max_length=10, choices=KINDS)
    ref = models.CharField(max_length=50)

    class Meta:
        unique_together = [('note', 'kind', 'ref')]
        indexes = [models.Index(fields=['kind', 'ref'], name='notes_mention_kind_ref_idx')]

    def __str__(self):
        return f'{self.note_id} -> {self.kind}:{self.ref}'
