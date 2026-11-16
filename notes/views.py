from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from . import mentions, system_prompts
from .models import Note, Notebook, NoteShare


def personal_tree(user, selected=None):
    """(roots, flat): the user's personal notebooks nested by parent. Each notebook gets `node_children`,
    `path` (`Personal / Jira Time Report / 2026 / 11`) and `open` (an ancestor of `selected` or `selected`)."""
    notebooks = list(Notebook.objects.filter(owner=user, is_system=False))
    by_id = {n.pk: n for n in notebooks}
    for n in notebooks:
        n.node_children = []
        n.open = False
    roots = []
    for n in notebooks:
        parent = by_id.get(n.parent_id)
        (parent.node_children if parent else roots).append(n)
    flat = []

    def walk(nodes, prefix):
        for n in nodes:
            n.path = f'{prefix}{n.name}'
            flat.append(n)
            walk(n.node_children, f'{n.path} / ')

    walk(roots, '')
    node = by_id.get(selected.pk) if selected else None
    while node:
        node.open = True
        node = by_id.get(node.parent_id)
    return roots, flat


def _note_perm(user, note):
    if note.key:   # system prompt: permission comes from the user, not from ownership or shares
        return system_prompts.perm_for(user)
    if note.owner == user:
        return 'owner'
    share = NoteShare.objects.filter(note=note, shared_with=user).first()
    return share.permission if share else None


class NoteListView(LoginRequiredMixin, View):
    def get(self, request, notebook_pk=None):
        if system_prompts.can_edit(request.user):
            system_prompts.ensure_all(request.user)
        selected_notebook = None
        if notebook_pk:
            selected_notebook = get_object_or_404(Notebook, pk=notebook_pk, owner=request.user, is_system=False)
        notebook_tree, notebooks = personal_tree(request.user, selected_notebook)
        if selected_notebook:
            # generated report files (2026-11, 2026-11_W45, ...) read in id order; ordinary notes by update time
            notes = selected_notebook.notes.select_related('notebook').order_by('file_id', '-updated_at')
        else:
            notes = Note.objects.filter(owner=request.user, key='').select_related('notebook')

        shared_notes = Note.objects.filter(
            shares__shared_with=request.user
        ).select_related('owner', 'notebook').order_by('-updated_at')

        return render(request, 'notes/note_list.html', {
            'notebooks': notebooks,
            'notebook_tree': notebook_tree,
            'notes': notes,
            'selected_notebook': selected_notebook,
            'shared_notes': shared_notes,
            'system_tree': system_prompts.system_tree(request.user),
        })


class NoteEditView(LoginRequiredMixin, View):
    def _resolve(self, request, pk, write):
        if pk:
            note = get_object_or_404(Note, pk=pk)
            perm = _note_perm(request.user, note)
            allowed = ('owner', 'write') if write else ('owner', 'write', 'read')
            if perm not in allowed:
                raise PermissionDenied
            return note, perm
        return None, 'owner'

    def get(self, request, pk=None):
        note, perm = self._resolve(request, pk, write=False)
        _, notebooks = personal_tree(request.user if note is None else note.owner)
        return render(request, 'notes/note_edit.html', {
            'note': note,
            'perm': perm,
            'read_only': perm == 'read',
            'notebooks': notebooks,
        })

    def post(self, request, pk=None):
        note, perm = self._resolve(request, pk, write=True)
        if note is None:
            note = Note(owner=request.user)

        note.title = request.POST.get('title', '').strip() or 'Untitled'
        note.body = request.POST.get('body', '')

        if perm == 'owner':
            notebook_pk = request.POST.get('notebook')
            if notebook_pk:
                note.notebook = get_object_or_404(Notebook, pk=notebook_pk, owner=note.owner, is_system=False)
            else:
                note.notebook = None

        note.save()
        mentions.sync_mentions(note)
        return redirect('note-edit', pk=note.pk)


class NoteDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        note = get_object_or_404(Note, pk=pk, owner=request.user)
        if note.is_system or note.key:
            raise PermissionDenied
        note.delete()
        return redirect('notes-list')


class NoteShareView(LoginRequiredMixin, View):
    def get(self, request, pk):
        note = get_object_or_404(Note, pk=pk, owner=request.user)
        if note.is_system or note.key:
            messages.error(request, 'System notes cannot be shared.')
            return redirect('note-edit', pk=pk)
        shares = note.shares.select_related('shared_with')
        shared_ids = shares.values_list('shared_with_id', flat=True)
        q = request.GET.get('q', '').strip()
        if len(q) >= 2:
            other_users = User.objects.exclude(pk=request.user.pk).exclude(
                pk__in=shared_ids
            ).filter(username__icontains=q).order_by('username')[:20]
        else:
            other_users = User.objects.none()
        return render(request, 'notes/note_share.html', {
            'note': note,
            'shares': shares,
            'other_users': other_users,
            'search_q': q,
        })

    def post(self, request, pk):
        note = get_object_or_404(Note, pk=pk, owner=request.user)
        if note.is_system or note.key:
            messages.error(request, 'System notes cannot be shared.')
            return redirect('note-edit', pk=pk)
        action = request.POST.get('action')

        if action == 'add':
            user_pk = request.POST.get('user_id')
            permission = request.POST.get('permission', NoteShare.PERM_READ)
            if user_pk and permission in (NoteShare.PERM_READ, NoteShare.PERM_WRITE):
                user = get_object_or_404(User, pk=user_pk)
                NoteShare.objects.update_or_create(
                    note=note, shared_with=user,
                    defaults={'permission': permission},
                )
        elif action == 'remove':
            NoteShare.objects.filter(pk=request.POST.get('share_id'), note=note).delete()
        elif action == 'update':
            permission = request.POST.get('permission')
            if permission in (NoteShare.PERM_READ, NoteShare.PERM_WRITE):
                NoteShare.objects.filter(pk=request.POST.get('share_id'), note=note).update(permission=permission)

        return redirect('note-share', pk=pk)


class NotebookCreateView(LoginRequiredMixin, View):
    def post(self, request):
        name = request.POST.get('name', '').strip()
        if name:
            Notebook.objects.get_or_create(owner=request.user, name=name, parent=None)
        return redirect('notes-list')


class NotebookDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        notebook = get_object_or_404(Notebook, pk=pk, owner=request.user, is_system=False)
        if not notebook.notes.exists() and not notebook.children.exists():
            notebook.delete()
        return redirect('notes-list')


class MentionSearchView(LoginRequiredMixin, View):
    """Autocomplete for `@`: only objects the user can see; credentials give name and type only."""
    def get(self, request):
        return JsonResponse({'results': mentions.search(request.user, request.GET.get('q', ''))})


class MentionResolveView(LoginRequiredMixin, View):
    """Preview: the body with each mention replaced by a chip resolved for the viewer."""
    def post(self, request):
        try:
            body = json.loads(request.body or b'{}').get('body', '')
        except (ValueError, AttributeError):
            body = ''
        if not isinstance(body, str):
            body = ''
        return JsonResponse({'body': mentions.render_mentions(request.user, body)})
