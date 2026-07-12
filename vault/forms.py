from django import forms
from django.db.models import Q

from core.models import Team

from .models import Container, ContainerAccess, Credential, Tag


class ContainerQuickCreateForm(forms.ModelForm):
    class Meta:
        model = Container
        fields = ['name', 'parent']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-select' if isinstance(field.widget, forms.Select) else 'form-control'
        accessible = Container.objects.filter(
            Q(access_grants__team__members=user, access_grants__access_level=ContainerAccess.ACCESS_READ_WRITE)
            | Q(created_by=user)
        ) if user else Container.objects.none()
        self.fields['parent'].queryset = accessible.distinct().order_by('name')
        self.fields['parent'].required = False
        self.fields['parent'].empty_label = '— No parent —'

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.created_by = self.user
        if commit:
            instance.save()
        return instance


class CredentialForm(forms.ModelForm):
    tags_input = forms.CharField(
        required=False,
        label='Tags',
        help_text='Comma-separated tag names.',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'tag1, tag2'}),
    )

    class Meta:
        model = Credential
        fields = [
            'name', 'credential_type', 'visibility', 'team', 'container',
            'url', 'username',
            'public_key', 'certificate_pem',
            'expiry_date',
        ]
        widgets = {
            'expiry_date': forms.DateInput(attrs={'type': 'date'}),
            'public_key': forms.Textarea(attrs={'rows': 4, 'spellcheck': 'false'}),
            'certificate_pem': forms.Textarea(attrs={'rows': 6, 'spellcheck': 'false'}),
        }

    # Secret fields handled separately (never round-tripped through form value)
    password = forms.CharField(required=False, label='Password', widget=forms.PasswordInput(render_value=False))
    private_key = forms.CharField(required=False, label='Private Key', widget=forms.Textarea(attrs={'rows': 6, 'spellcheck': 'false'}))
    passphrase = forms.CharField(required=False, label='Passphrase', widget=forms.PasswordInput(render_value=False))

    # Notes: encrypted independently, own sharing toggle. Not a direct model
    # field passthrough — the model stores ciphertext (encrypted_notes).
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))
    notes_shared = forms.BooleanField(
        required=False, label='Share notes with team (readable/editable by read-write members)',
    )

    def __init__(self, *args, user=None, show_notes=True, can_toggle_notes_shared=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self._show_notes = show_notes
        self._apply_bootstrap()
        self.fields['team'].queryset = Team.objects.filter(members=user) if user else Team.objects.none()
        self.fields['team'].required = False

        # Container choices: containers the user can actually write into
        # (RW access via some team, or they created it), plus the
        # credential's current container if editing — always keep the
        # current value selectable even if access has since lapsed, so an
        # unrelated save doesn't silently clear it.
        if user:
            accessible = Container.objects.filter(
                Q(access_grants__team__members=user, access_grants__access_level=ContainerAccess.ACCESS_READ_WRITE)
                | Q(created_by=user)
            )
            if self.instance.pk and self.instance.container_id:
                accessible = accessible | Container.objects.filter(pk=self.instance.container_id)
            self.fields['container'].queryset = accessible.distinct().order_by('name')
        else:
            self.fields['container'].queryset = Container.objects.none()
        self.fields['container'].required = False
        self.fields['container'].empty_label = '— Personal (no container) —'

        if self.instance.pk:
            self.fields['tags_input'].initial = ', '.join(
                self.instance.tags.values_list('name', flat=True)
            )
            self.fields['notes_shared'].initial = self.instance.notes_shared
            if show_notes:
                from .crypto import decrypt_notes_for_credential
                self._original_notes = decrypt_notes_for_credential(self.instance, user, self.instance.encrypted_notes)
                self.fields['notes'].initial = self._original_notes
            else:
                self._original_notes = None
                self.fields['notes'].disabled = True
                self.fields['notes'].help_text = 'Notes are private to the owner.'
            self._original_notes_shared = self.instance.notes_shared
        else:
            self._original_notes = ''
            self._original_notes_shared = False
        if not can_toggle_notes_shared:
            self.fields['notes_shared'].disabled = True

        # Boundary-determining fields, captured here (before any binding/
        # validation) for the same reason as _original_notes above: Django's
        # ModelForm._post_clean() (called inside is_valid(), before save()
        # ever runs) already mutates self.instance's fields with the
        # submitted values. Reading self.instance.container_id etc. at the
        # START of save() would read the NEW value, not the old one —
        # comparing new-vs-new always looks unchanged. Must capture here,
        # and must use these captured values (not self.instance) for any
        # "decrypt under the OLD boundary" step in save() too.
        self._original_container_id = self.instance.container_id
        self._original_visibility = self.instance.visibility
        self._original_team_id = self.instance.team_id
        self._original_owner = self.instance.owner if self.instance.pk else None

    def _apply_bootstrap(self):
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = 'form-check-input'
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs['class'] = 'form-select'
            elif 'class' not in widget.attrs:
                widget.attrs['class'] = 'form-control'

    def _decrypt_under_old_secret_boundary(self, container_id, visibility, team_id, token):
        """Resolve and decrypt using EXPLICIT old boundary values, not
        self.instance (unreliable mid-save, see save()'s comment) and not
        crypto._resolve_credential_boundary (which reads a live instance).
        Mirrors that function's container > team > personal priority.
        """
        from .crypto import decrypt_for_container, decrypt_for_team, decrypt_for_user
        if container_id:
            container = Container.objects.get(pk=container_id)
            return decrypt_for_container(container, self.user, token)
        if visibility == Credential.VIS_TEAM and team_id:
            team = Team.objects.get(pk=team_id)
            return decrypt_for_team(team, self.user, token)
        return decrypt_for_user(self._original_owner, token)

    def _decrypt_under_old_notes_boundary(self, container_id, notes_shared, token):
        from .crypto import decrypt_for_container, decrypt_for_user
        if notes_shared and container_id:
            container = Container.objects.get(pk=container_id)
            return decrypt_for_container(container, self.user, token)
        return decrypt_for_user(self._original_owner, token)

    def save(self, commit=True):
        from .crypto import encrypt_for_credential, encrypt_notes_for_credential

        secret_fields = ['encrypted_password', 'encrypted_private_key', 'encrypted_passphrase']
        plaintext_field_names = {
            'encrypted_password': 'password',
            'encrypted_private_key': 'private_key',
            'encrypted_passphrase': 'passphrase',
        }

        # Any of container/visibility/team can independently determine the
        # SECRET boundary (see crypto._resolve_credential_boundary). Compare
        # against the values captured in __init__ — self.instance itself is
        # unreliable here: Django's ModelForm._post_clean() (run inside
        # is_valid(), before save() is ever called) already mutates
        # self.instance's fields with the submitted values, so reading
        # self.instance.container_id at this point would read the NEW value
        # and always report "unchanged".
        old_container_id = self._original_container_id
        old_visibility = self._original_visibility
        old_team_id = self._original_team_id

        new_container = self.cleaned_data.get('container')
        new_container_id = new_container.pk if new_container else None
        new_team = self.cleaned_data.get('team')
        new_team_id = new_team.pk if new_team else None
        new_visibility = self.cleaned_data.get('visibility')

        secret_boundary_changing = (
            new_container_id != old_container_id
            or new_visibility != old_visibility
            or new_team_id != old_team_id
        )

        # For any secret field NOT getting a freshly-typed value in this
        # submission, and the boundary is changing: decrypt it under the OLD
        # boundary now (resolved from the captured old_* values, NOT from
        # self.instance — same reliability issue as above), so it can be
        # re-encrypted under the NEW boundary afterward. A field that DID
        # get a fresh value is simply encrypted under the new boundary below
        # — no need to touch its old ciphertext at all.
        stashed_plaintexts = {}
        if secret_boundary_changing and self.instance.pk:
            for field in secret_fields:
                if not self.cleaned_data.get(plaintext_field_names[field]):
                    token = getattr(self.instance, field)
                    if token:
                        stashed_plaintexts[field] = self._decrypt_under_old_secret_boundary(
                            old_container_id, old_visibility, old_team_id, token,
                        )

        # Notes boundary depends only on container_id (+ notes_shared,
        # handled in the existing text_changed/share_changed check below) —
        # independent of visibility/team. Only need to stash the old
        # plaintext if the submitted text ISN'T also changing; if it is, the
        # new text gets encrypted fresh under the new boundary regardless.
        notes_boundary_changing = self._show_notes and (new_container_id != old_container_id)
        stashed_notes = None
        if notes_boundary_changing and self.instance.pk and self.instance.encrypted_notes:
            if self.cleaned_data.get('notes', '') == self._original_notes:
                stashed_notes = self._decrypt_under_old_notes_boundary(
                    old_container_id, self._original_notes_shared, self.instance.encrypted_notes,
                )

        instance = super().save(commit=False)
        if not instance.owner_id:
            # New credential — owner isn't assigned yet at this point (the
            # view sets it after save(commit=False) returns), but boundary
            # resolution for encryption needs it now.
            instance.owner = self.user

        if self.cleaned_data.get('password'):
            instance.encrypted_password = encrypt_for_credential(instance, self.user, self.cleaned_data['password'])
        elif 'encrypted_password' in stashed_plaintexts:
            instance.encrypted_password = encrypt_for_credential(instance, self.user, stashed_plaintexts['encrypted_password'])

        if self.cleaned_data.get('private_key'):
            instance.encrypted_private_key = encrypt_for_credential(instance, self.user, self.cleaned_data['private_key'])
        elif 'encrypted_private_key' in stashed_plaintexts:
            instance.encrypted_private_key = encrypt_for_credential(instance, self.user, stashed_plaintexts['encrypted_private_key'])

        if self.cleaned_data.get('passphrase'):
            instance.encrypted_passphrase = encrypt_for_credential(instance, self.user, self.cleaned_data['passphrase'])
        elif 'encrypted_passphrase' in stashed_plaintexts:
            instance.encrypted_passphrase = encrypt_for_credential(instance, self.user, stashed_plaintexts['encrypted_passphrase'])

        # notes_shared isn't in Meta.fields (it's declared explicitly, like the
        # secret fields), so super().save() doesn't apply it automatically.
        # A disabled field (non-owner) resolves to its initial value here,
        # never the submitted POST value — this is what actually blocks a
        # non-owner from toggling it via a crafted request, not just the UI.
        instance.notes_shared = self.cleaned_data.get('notes_shared', False)

        if self._show_notes:
            new_notes = self.cleaned_data.get('notes', '')
            text_changed = new_notes != self._original_notes
            share_changed = bool(instance.notes_shared) != bool(self._original_notes_shared)
            if text_changed or share_changed or notes_boundary_changing:
                plaintext_to_encrypt = new_notes if text_changed else (
                    stashed_notes if stashed_notes is not None else new_notes
                )
                instance.encrypted_notes = encrypt_notes_for_credential(instance, self.user, plaintext_to_encrypt)

        if commit:
            instance.save()
            self._save_tags(instance)
        return instance

    def _save_tags(self, instance):
        raw = self.cleaned_data.get('tags_input', '')
        names = [n.strip() for n in raw.split(',') if n.strip()]
        tags = [Tag.objects.get_or_create(name=n)[0] for n in names]
        instance.tags.set(tags)
