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
        Q(owner=user)
        | Q(visibility='team', team__members=user)
        | Q(container__access_grants__team__members=user)
    ).distinct().prefetch_related('tags')


def _can_access(user, credential):
    if credential.owner == user:
        return True
    if credential.visibility == 'team' and credential.team and credential.team.members.filter(pk=user.pk).exists():
        return True
    if credential.container_id and credential.container.access_grants.filter(team__members=user).exists():
        return True
    return False


def _can_edit(user, credential):
    if credential.owner == user:
        return True
    if credential.container_id and credential.container.access_grants.filter(
        team__members=user, access_level='read_write',
    ).exists():
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
        credential._changed_by = request.user
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
    if not _can_edit(request.user, credential):
        raise PermissionDenied
    form = CredentialForm(request.POST or None, instance=credential, user=request.user)
    if form.is_valid():
        obj = form.save(commit=False)
        obj._changed_by = request.user
        obj.save()
        form._save_tags(obj)
        return redirect('vault-list')
    history = credential.versions.select_related('changed_by')[:20]
    return render(request, 'vault/credential_form.html', {
        'form': form,
        'title': 'Edit Credential',
        'credential': credential,
        'history': history,
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
    field = 'encrypted_password' if credential.credential_type == Credential.TYPE_PASSWORD else 'encrypted_private_key'
    token = getattr(credential, field)
    if credential.owner == request.user:
        from .crypto import decrypt_for_user
        secret = decrypt_for_user(credential.owner, token)
    elif credential.container_id:
        from .crypto import decrypt_for_container
        secret = decrypt_for_container(credential.container, request.user, token)
    else:
        # Legacy path: team credential never migrated into a container
        # (shouldn't happen post-migration, kept defensively).
        from .crypto import decrypt_for_team
        secret = decrypt_for_team(credential.team, request.user, token)
    return JsonResponse({'secret': secret})


@login_required
def import_credentials(request):
    error = None
    if request.method == 'POST':
        uploaded = request.FILES.get('file')
        if not uploaded:
            error = 'Please select a file.'
        else:
            filename = uploaded.name.lower()
            try:
                if filename.endswith('.kdbx'):
                    from .importer import parse_kdbx
                    import tempfile, os
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.kdbx') as tmp:
                        for chunk in uploaded.chunks():
                            tmp.write(chunk)
                        tmp_path = tmp.name
                    try:
                        entries = parse_kdbx(tmp_path, request.POST.get('password', ''))
                    finally:
                        os.unlink(tmp_path)
                    source_tag = 'keepass'
                elif filename.endswith('.xml'):
                    from .importer import parse_xml
                    entries = parse_xml(uploaded)
                    source_tag = 'keepassx'
                else:
                    error = 'Unsupported file type. Use .kdbx or .xml.'
                    entries = None

                if entries is not None:
                    existing = set(
                        Credential.objects.filter(owner=request.user).values_list('name', flat=True)
                    )
                    for e in entries:
                        e['duplicate'] = e['name'] in existing
                        e['source_tag'] = source_tag
                    request.session['vault_import'] = entries
                    return render(request, 'vault/import_preview.html', {
                        'entries': entries,
                        'source_tag': source_tag,
                        'new_count': sum(1 for e in entries if not e['duplicate']),
                        'skip_count': sum(1 for e in entries if e['duplicate']),
                    })
            except Exception as exc:
                error = f'Failed to parse file: {exc}'

    return render(request, 'vault/import_form.html', {'error': error})


@login_required
@require_POST
def import_confirm(request):
    entries = request.session.pop('vault_import', None)
    if not entries:
        return redirect('vault-import')

    existing = set(Credential.objects.filter(owner=request.user).values_list('name', flat=True))
    from .crypto import encrypt_for_user

    for e in entries:
        if e['name'] in existing:
            continue
        cred = Credential(
            owner=request.user,
            credential_type=Credential.TYPE_PASSWORD,
            name=e['name'],
            url=e['url'],
            username=e['username'],
            notes=e['notes'],
            encrypted_password=encrypt_for_user(request.user, e['password']) if e['password'] else '',
        )
        cred._changed_by = request.user
        cred.save()
        tag_names = list(e.get('tags') or [])
        if e.get('source_tag'):
            tag_names.append(e['source_tag'])
        if tag_names:
            tags = [Tag.objects.get_or_create(name=t)[0] for t in tag_names]
            cred.tags.set(tags)

    return redirect('vault-list')
