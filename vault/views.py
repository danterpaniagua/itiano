from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import CredentialForm
from .models import Credential, Tag


def _visible_credentials(user):
    from django.db.models import Q
    return Credential.objects.filter(
        Q(owner=user) | Q(visibility='team', team__members=user)
    ).distinct().prefetch_related('tags')


def _can_access(user, credential):
    if credential.owner == user:
        return True
    if credential.visibility == 'team' and credential.team and credential.team.members.filter(pk=user.pk).exists():
        return True
    return False


@login_required
def credential_list(request):
    tag_filter = request.GET.get('tag', '')
    credentials = _visible_credentials(request.user)
    if tag_filter:
        credentials = credentials.filter(tags__name=tag_filter)
    all_tags = Tag.objects.filter(credentials__in=_visible_credentials(request.user)).distinct()
    return render(request, 'vault/credential_list.html', {
        'credentials': credentials,
        'all_tags': all_tags,
        'tag_filter': tag_filter,
    })


@login_required
def credential_create(request):
    form = CredentialForm(request.POST or None, user=request.user)
    if form.is_valid():
        credential = form.save(commit=False)
        credential.owner = request.user
        credential.save()
        form._save_tags(credential)
        return redirect('vault-list')
    return render(request, 'vault/credential_form.html', {
        'form': form,
        'title': 'New Credential',
    })


@login_required
def credential_edit(request, pk):
    credential = get_object_or_404(Credential, pk=pk)
    if credential.owner != request.user:
        raise PermissionDenied
    form = CredentialForm(request.POST or None, instance=credential, user=request.user)
    if form.is_valid():
        form.save()
        return redirect('vault-list')
    return render(request, 'vault/credential_form.html', {
        'form': form,
        'title': 'Edit Credential',
        'credential': credential,
    })


@login_required
@require_POST
def credential_delete(request, pk):
    credential = get_object_or_404(Credential, pk=pk)
    if credential.owner != request.user:
        raise PermissionDenied
    credential.delete()
    return redirect('vault-list')


@login_required
@require_POST
def credential_copy(request, pk):
    credential = get_object_or_404(Credential, pk=pk)
    if not _can_access(request.user, credential):
        raise PermissionDenied
    from .crypto import decrypt_for_user
    if credential.credential_type == Credential.TYPE_PASSWORD:
        secret = decrypt_for_user(credential.owner, credential.encrypted_password)
    else:
        secret = decrypt_for_user(credential.owner, credential.encrypted_private_key)
    return JsonResponse({'secret': secret})
