import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .models import ClipboardEntry


@login_required
def clipboard(request):
    entry, _ = ClipboardEntry.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        entry.set_content(request.POST.get('content', ''))
        entry.save()
        messages.success(request, 'Saved.')
        return redirect('clipboard')

    return render(request, 'clipboard/clipboard.html', {
        'content': entry.get_decrypted(),
    })


@login_required
@require_GET
def clipboard_content(request):
    entry, _ = ClipboardEntry.objects.get_or_create(user=request.user)
    return JsonResponse({'content': entry.get_decrypted()})


@login_required
@require_POST
def clipboard_save(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
    entry, _ = ClipboardEntry.objects.get_or_create(user=request.user)
    entry.set_content(data.get('content', ''))
    entry.save()
    return JsonResponse({'ok': True})
