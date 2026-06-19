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
            'notes', 'expiry_date',
        ]
        widgets = {
            'expiry_date': forms.DateInput(attrs={'type': 'date'}),
            'public_key': forms.Textarea(attrs={'rows': 4, 'spellcheck': 'false'}),
            'certificate_pem': forms.Textarea(attrs={'rows': 6, 'spellcheck': 'false'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    # Secret fields handled separately (never round-tripped through form value)
    password = forms.CharField(required=False, label='Password', widget=forms.PasswordInput(render_value=False))
    private_key = forms.CharField(required=False, label='Private Key', widget=forms.Textarea(attrs={'rows': 6, 'spellcheck': 'false'}))
    passphrase = forms.CharField(required=False, label='Passphrase', widget=forms.PasswordInput(render_value=False))

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self._apply_bootstrap()
        self.fields['team'].queryset = Team.objects.filter(members=user) if user else Team.objects.none()
        self.fields['team'].required = False
        if self.instance.pk:
            self.fields['tags_input'].initial = ', '.join(
                self.instance.tags.values_list('name', flat=True)
            )

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
        from .crypto import encrypt_for_user
        if self.cleaned_data.get('password'):
            instance.encrypted_password = encrypt_for_user(self.user, self.cleaned_data['password'])
        if self.cleaned_data.get('private_key'):
            instance.encrypted_private_key = encrypt_for_user(self.user, self.cleaned_data['private_key'])
        if self.cleaned_data.get('passphrase'):
            instance.encrypted_passphrase = encrypt_for_user(self.user, self.cleaned_data['passphrase'])
        if commit:
            instance.save()
            self._save_tags(instance)
        return instance

    def _save_tags(self, instance):
        raw = self.cleaned_data.get('tags_input', '')
        names = [n.strip() for n in raw.split(',') if n.strip()]
        tags = [Tag.objects.get_or_create(name=n)[0] for n in names]
        instance.tags.set(tags)
