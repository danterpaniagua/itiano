from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .models import Note, Notebook, NoteShare


def _note_perm(user, note):
    if note.owner == user:
        return 'owner'
    share = NoteShare.objects.filter(note=note, shared_with=user).first()
    return share.permission if share else None


class NoteListView(LoginRequiredMixin, View):
    def get(self, request, notebook_pk=None):
        notebooks = Notebook.objects.filter(owner=request.user)
        selected_notebook = None
        if notebook_pk:
            selected_notebook = get_object_or_404(Notebook, pk=notebook_pk, owner=request.user)
            notes = selected_notebook.notes.select_related('notebook')
        else:
            notes = Note.objects.filter(owner=request.user).select_related('notebook')

        shared_notes = Note.objects.filter(
            shares__shared_with=request.user
        ).select_related('owner', 'notebook').order_by('-updated_at')

        return render(request, 'notes/note_list.html', {
            'notebooks': notebooks,
            'notes': notes,
            'selected_notebook': selected_notebook,
            'shared_notes': shared_notes,
        })


class NoteEditView(LoginRequiredMixin, View):
    def _resolve(self, request, pk):
        if pk:
            note = get_object_or_404(Note, pk=pk)
            perm = _note_perm(request.user, note)
            if perm not in ('owner', 'write'):
                raise PermissionDenied
            return note, perm
        return None, 'owner'

    def get(self, request, pk=None):
        note, perm = self._resolve(request, pk)
        notebooks = Notebook.objects.filter(owner=request.user if note is None else note.owner)
        return render(request, 'notes/note_edit.html', {
            'note': note,
            'perm': perm,
            'notebooks': notebooks,
        })

    def post(self, request, pk=None):
        note, perm = self._resolve(request, pk)
        if note is None:
            note = Note(owner=request.user)

        note.title = request.POST.get('title', '').strip() or 'Untitled'
        note.body = request.POST.get('body', '')

        if perm == 'owner':
            notebook_pk = request.POST.get('notebook')
            if notebook_pk:
                note.notebook = get_object_or_404(Notebook, pk=notebook_pk, owner=note.owner)
            else:
                note.notebook = None

        note.save()
        return redirect('note-edit', pk=note.pk)


class NoteDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        note = get_object_or_404(Note, pk=pk, owner=request.user)
        if note.is_system:
            raise PermissionDenied
        note.delete()
        return redirect('notes-list')


class NoteShareView(LoginRequiredMixin, View):
    def get(self, request, pk):
        note = get_object_or_404(Note, pk=pk, owner=request.user)
        if note.is_system:
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
        if note.is_system:
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
            Notebook.objects.get_or_create(owner=request.user, name=name)
        return redirect('notes-list')


class NotebookDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        notebook = get_object_or_404(Notebook, pk=pk, owner=request.user)
        if not notebook.notes.exists():
            notebook.delete()
        return redirect('notes-list')
