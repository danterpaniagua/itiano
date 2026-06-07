from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

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
