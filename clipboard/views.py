import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .utils import get_or_create_clipboard_note


@login_required
def clipboard(request):
    note = get_or_create_clipboard_note(request.user)
    return redirect(reverse('note-edit', args=[note.pk]))


@login_required
@require_GET
def clipboard_content(request):
    note = get_or_create_clipboard_note(request.user)
    return JsonResponse({'content': note.body})


@login_required
@require_POST
def clipboard_save(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
    note = get_or_create_clipboard_note(request.user)
    new_content = data.get('content', '')
    if new_content == note.body:
        return JsonResponse({'ok': True, 'changed': False})
    note.body = new_content
    note.save(update_fields=['body', 'updated_at'])
    return JsonResponse({'ok': True, 'changed': True})
