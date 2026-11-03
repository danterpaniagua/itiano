"""System-wide prompts stored as notes (v5.19.0).

Folder tree (every folder has a display name and a snake_case id):

    System Prompts (system_prompts)
    └─ Itiano (itiano)                     one folder per project
       └─ prompt_time_report               a note, found by its id, never by title

The prompt id is `prompt_` + the feature's URL path in snake_case. Features register their prompt in
PROMPTS with a built-in default; the folders and the note are created from it the first time an admin
opens Notes, and `get_prompt` falls back to the default when the note is missing or empty.
"""
import re

from .models import Note, Notebook

ROOT_KEY = 'system_prompts'
ROOT_NAME = 'System Prompts'
PROJECTS = {'itiano': 'Itiano'}
PROMPT_ID_RE = re.compile(r'^prompt_[a-z0-9]+(_[a-z0-9]+)*$')
VIEW_PERMISSION = 'notes.view_system_prompts'

# id -> {'project', 'title', 'default'}; features add their entry here (empty until v5.21.0).
PROMPTS = {}


def register(prompt_id, project, title, default):
    if not PROMPT_ID_RE.match(prompt_id):
        raise ValueError(f'Invalid prompt id {prompt_id!r}: use prompt_<feature> in snake_case.')
    if project not in PROJECTS:
        raise ValueError(f'Unknown project folder {project!r}.')
    PROMPTS[prompt_id] = {'project': project, 'title': title, 'default': default}


def can_edit(user):
    """Only system admins edit a system prompt."""
    return bool(user.is_authenticated and user.is_staff)


def can_view(user):
    """System admins, managers and users granted `notes.view_system_prompts` (the viewers group)."""
    if not user.is_authenticated:
        return False
    if user.is_staff or user.has_perm(VIEW_PERMISSION):
        return True
    from itsm.permissions import get_role
    return get_role(user) == 'manager'


def perm_for(user):
    """'write' for admins, 'read' for the other viewers, None for everyone else."""
    if can_edit(user):
        return 'write'
    return 'read' if can_view(user) else None


def ensure_prompt(prompt_id, owner):
    """Create the folders and the note for a registered prompt if they do not exist yet."""
    spec = PROMPTS[prompt_id]
    root, _ = Notebook.objects.get_or_create(
        key=ROOT_KEY, defaults={'name': ROOT_NAME, 'owner': owner, 'is_system': True},
    )
    project, _ = Notebook.objects.get_or_create(
        key=spec['project'],
        defaults={'name': PROJECTS[spec['project']], 'owner': owner, 'is_system': True, 'parent': root},
    )
    note, _ = Note.objects.get_or_create(
        key=prompt_id,
        defaults={'title': spec['title'], 'body': spec['default'], 'owner': owner, 'notebook': project},
    )
    return note


def ensure_all(owner):
    for prompt_id in PROMPTS:
        ensure_prompt(prompt_id, owner)


def get_prompt(prompt_id):
    """The edited text of a prompt, or its built-in default when the note is missing or empty."""
    spec = PROMPTS[prompt_id]
    note = Note.objects.filter(key=prompt_id).first()
    return note.body if note and note.body.strip() else spec['default']


def system_tree(user):
    """[{'name', 'key', 'notes': [...]}] per project folder for the sidebar.

    Allowed users always get the registered project folders (empty ones show "no prompts yet");
    users who may not view system prompts get [].
    """
    if not can_view(user):
        return []
    projects = {key: {'name': name, 'key': key, 'notes': []} for key, name in PROJECTS.items()}
    for note in Note.objects.exclude(key='').select_related('notebook').order_by('title'):
        key = note.notebook.key if note.notebook else ''
        entry = projects.setdefault(key, {'name': note.notebook.name if note.notebook else '', 'key': key, 'notes': []})
        entry['notes'].append(note)
    return sorted(projects.values(), key=lambda p: p['name'])
