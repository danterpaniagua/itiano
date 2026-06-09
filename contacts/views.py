import json
import urllib.request
import urllib.error

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import models
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Contact, ContactChannel


def _staff_required(request):
    if not request.user.is_staff:
        raise PermissionDenied


@login_required
def contact_list(request):
    _staff_required(request)
    contacts = Contact.objects.select_related('user').prefetch_related('channels')
    return render(request, 'contacts/contact_list.html', {'contacts': contacts})


@login_required
def contact_detail(request, pk):
    _staff_required(request)
    contact = get_object_or_404(Contact, pk=pk)
    return render(request, 'contacts/contact_detail.html', {'contact': contact})


@login_required
def contact_create(request):
    _staff_required(request)
    if request.method == 'POST':
        contact = _save_contact(request, Contact())
        return redirect('contact-detail', pk=contact.pk)
    return render(request, 'contacts/contact_form.html', {
        'title': 'New Contact',
        'users': _unlinked_users(),
    })


@login_required
def contact_edit(request, pk):
    _staff_required(request)
    contact = get_object_or_404(Contact, pk=pk)
    if request.method == 'POST':
        _save_contact(request, contact)
        return redirect('contact-detail', pk=contact.pk)
    return render(request, 'contacts/contact_form.html', {
        'title': 'Edit Contact',
        'contact': contact,
        'users': _unlinked_users(exclude_pk=contact.user_id),
    })


@login_required
def contact_delete(request, pk):
    _staff_required(request)
    contact = get_object_or_404(Contact, pk=pk)
    if request.method == 'POST':
        contact.delete()
        return redirect('contact-list')
    return render(request, 'contacts/contact_confirm_delete.html', {'contact': contact})


@login_required
def channel_create(request, contact_pk):
    _staff_required(request)
    contact = get_object_or_404(Contact, pk=contact_pk)
    if request.method == 'POST':
        _save_channel(request, ContactChannel(contact=contact))
        return redirect('contact-detail', pk=contact_pk)
    return render(request, 'contacts/channel_form.html', {
        'title': 'Add Channel',
        'contact': contact,
        'channel': None,
    })


@login_required
def channel_edit(request, contact_pk, pk):
    _staff_required(request)
    contact = get_object_or_404(Contact, pk=contact_pk)
    channel = get_object_or_404(ContactChannel, pk=pk, contact=contact)
    if request.method == 'POST':
        _save_channel(request, channel)
        return redirect('contact-detail', pk=contact_pk)
    return render(request, 'contacts/channel_form.html', {
        'title': 'Edit Channel',
        'contact': contact,
        'channel': channel,
    })


@login_required
def channel_delete(request, contact_pk, pk):
    _staff_required(request)
    contact = get_object_or_404(Contact, pk=contact_pk)
    channel = get_object_or_404(ContactChannel, pk=pk, contact=contact)
    if request.method == 'POST':
        channel.delete()
    return redirect('contact-detail', pk=contact_pk)


@login_required
@require_POST
def channel_test(request, contact_pk, pk):
    _staff_required(request)
    contact = get_object_or_404(Contact, pk=contact_pk)
    channel = get_object_or_404(ContactChannel, pk=pk, contact=contact)

    if channel.type != ContactChannel.TYPE_POST:
        return JsonResponse({'error': 'Only POST channels can be tested.'}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    url = channel.url
    body = data.get('body', channel.body).encode('utf-8')
    headers = dict(channel.headers)
    headers.update(data.get('headers', {}))
    headers.setdefault('Content-Type', 'application/json')

    try:
        req = urllib.request.Request(url, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=10) as resp:
            response_body = resp.read(4096).decode('utf-8', errors='replace')
            return JsonResponse({'status_code': resp.status, 'body': response_body})
    except urllib.error.HTTPError as e:
        response_body = e.read(4096).decode('utf-8', errors='replace')
        return JsonResponse({'status_code': e.code, 'body': response_body})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=502)


# --- helpers ---

def _unlinked_users(exclude_pk=None):
    if exclude_pk:
        return User.objects.filter(
            models.Q(contact__isnull=True) | models.Q(pk=exclude_pk)
        ).order_by('username')
    return User.objects.filter(contact__isnull=True).order_by('username')


def _save_contact(request, contact):
    contact.first_name = request.POST.get('first_name', '').strip()
    contact.last_name = request.POST.get('last_name', '').strip()
    user_pk = request.POST.get('user')
    contact.user = User.objects.filter(pk=user_pk).first() if user_pk else None
    contact.save()
    return contact


def _save_channel(request, channel):
    channel.type = request.POST.get('type', ContactChannel.TYPE_EMAIL)
    channel.label = request.POST.get('label', '').strip()
    channel.is_primary = bool(request.POST.get('is_primary'))
    channel.value = request.POST.get('value', '').strip()
    channel.url = request.POST.get('url', '').strip()
    channel.body = request.POST.get('body', '').strip()

    keys = request.POST.getlist('header_key')
    vals = request.POST.getlist('header_value')
    channel.headers = {k: v for k, v in zip(keys, vals) if k.strip()}

    channel.save()
    return channel
