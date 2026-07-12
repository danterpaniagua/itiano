from django import forms

from .models import Credential, Tag, Team


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
            'name', 'credential_type', 'visibility', 'team',
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

    def _apply_bootstrap(self):
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = 'form-check-input'
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs['class'] = 'form-select'
            elif 'class' not in widget.attrs:
                widget.attrs['class'] = 'form-control'

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.owner_id:
            # New credential — owner isn't assigned yet at this point (the
            # view sets it after save(commit=False) returns), but boundary
            # resolution for encryption needs it now.
            instance.owner = self.user

        from .crypto import encrypt_for_credential, encrypt_notes_for_credential
        if self.cleaned_data.get('password'):
            instance.encrypted_password = encrypt_for_credential(instance, self.user, self.cleaned_data['password'])
        if self.cleaned_data.get('private_key'):
            instance.encrypted_private_key = encrypt_for_credential(instance, self.user, self.cleaned_data['private_key'])
        if self.cleaned_data.get('passphrase'):
            instance.encrypted_passphrase = encrypt_for_credential(instance, self.user, self.cleaned_data['passphrase'])

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
            if text_changed or share_changed:
                instance.encrypted_notes = encrypt_notes_for_credential(instance, self.user, new_notes)

        if commit:
            instance.save()
            self._save_tags(instance)
        return instance

    def _save_tags(self, instance):
        raw = self.cleaned_data.get('tags_input', '')
        names = [n.strip() for n in raw.split(',') if n.strip()]
        tags = [Tag.objects.get_or_create(name=n)[0] for n in names]
        instance.tags.set(tags)
