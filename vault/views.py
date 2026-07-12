from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import ContainerQuickCreateForm, CredentialForm
from .models import Container, Credential, Tag


def _visible_credentials(user):
    from django.db.models import Q
    return Credential.objects.filter(
        Q(owner=user)
        | Q(visibility='team', team__members=user)
        | Q(container__access_grants__team__members=user)
    ).exclude(is_deleted=True).distinct().prefetch_related('tags')


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
    q = request.GET.get('q', '').strip()
    container_filter = request.GET.get('container', '')

    credentials = _visible_credentials(request.user)
    if tag_filter:
        credentials = credentials.filter(tags__name=tag_filter)
    if q:
        credentials = credentials.filter(
            Q(name__icontains=q) | Q(username__icontains=q) | Q(url__icontains=q)
        )
    if container_filter == 'none':
        credentials = credentials.filter(container__isnull=True)
    elif container_filter:
        credentials = credentials.filter(container_id=container_filter)

    credentials = list(credentials)
    for c in credentials:
        c.can_edit = _can_edit(request.user, c)

    all_tags = Tag.objects.filter(credentials__in=_visible_credentials(request.user)).distinct()

    # Sidebar: containers this user has some access to (any ContainerAccess
    # level via a team, or they created it) — not every container that
    # exists globally. Per-node counts reflect what THIS user can see
    # (_visible_credentials), not the container's total credential count.
    # Flattened into depth-first order with a `.depth` attribute here in
    # Python rather than fighting Django templates' limited recursion —
    # the template just indents by depth, no recursive {% include %}.
    visible_all = _visible_credentials(request.user)
    personal_count = visible_all.filter(container__isnull=True).count()
    accessible_containers = list(
        Container.objects.filter(
            Q(access_grants__team__members=request.user) | Q(created_by=request.user)
        ).distinct().select_related('parent').order_by('name')
    )
    for c in accessible_containers:
        c.visible_count = visible_all.filter(container_id=c.pk).count()

    children_by_parent = {}
    for c in accessible_containers:
        children_by_parent.setdefault(c.parent_id, []).append(c)

    sidebar_containers = []

    def _walk(parent_id, depth):
        for node in children_by_parent.get(parent_id, []):
            node.depth = depth
            sidebar_containers.append(node)
            _walk(node.pk, depth + 1)

    _walk(None, 0)

    return render(request, 'vault/credential_list.html', {
        'credentials': credentials,
        'all_tags': all_tags,
        'tag_filter': tag_filter,
        'q': q,
        'container_filter': container_filter,
        'sidebar_containers': sidebar_containers,
        'personal_count': personal_count,
        'total_visible_count': visible_all.count(),
    })


@login_required
def container_create(request):
    form = ContainerQuickCreateForm(request.POST or None, user=request.user)
    if form.is_valid():
        container = form.save()
        return redirect(f"{reverse('vault-list')}?container={container.pk}")
    return render(request, 'vault/container_form.html', {'form': form})


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
    credential = get_object_or_404(Credential, pk=pk, is_deleted=False)
    if not _can_edit(request.user, credential):
        raise PermissionDenied
    is_owner = credential.owner == request.user
    show_notes = is_owner or credential.notes_shared
    form = CredentialForm(
        request.POST or None, instance=credential, user=request.user,
        show_notes=show_notes, can_toggle_notes_shared=is_owner,
    )
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
    credential = get_object_or_404(Credential, pk=pk, is_deleted=False)
    if not _can_edit(request.user, credential):
        raise PermissionDenied
    credential.is_deleted = True
    credential._changed_by = request.user
    credential.save(update_fields=['is_deleted'])
    return redirect('vault-list')


@login_required
@require_POST
def credential_copy(request, pk):
    credential = get_object_or_404(Credential, pk=pk, is_deleted=False)
    if not _can_access(request.user, credential):
        raise PermissionDenied
    field = 'encrypted_password' if credential.credential_type == Credential.TYPE_PASSWORD else 'encrypted_private_key'
    token = getattr(credential, field)
    from .crypto import decrypt_for_credential
    secret = decrypt_for_credential(credential, request.user, token)
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
                        Credential.objects.filter(owner=request.user).exclude(is_deleted=True).values_list('name', flat=True)
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

    existing = set(Credential.objects.filter(owner=request.user).exclude(is_deleted=True).values_list('name', flat=True))
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
