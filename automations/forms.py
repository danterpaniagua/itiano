from django import forms

from .models import Action, Trigger

_JSON_FIELDS = ('field_mappings', 'filter')


def _apply_bootstrap(form):
    for name, field in form.fields.items():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs['class'] = 'form-check-input'
        elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
            widget.attrs['class'] = 'form-select'
        else:
            widget.attrs['class'] = 'form-control' + (' font-monospace' if name in _JSON_FIELDS else '')
        if name in _JSON_FIELDS:
            widget.attrs.update({'rows': 8, 'spellcheck': 'false'})


class ActionForm(forms.ModelForm):
    class Meta:
        model = Action
        fields = ['name', 'action_type', 'description_format', 'field_mappings', 'tag_expressions', 'system_user', 'dedup_expression', 'is_active']
        widgets = {
            'tag_expressions': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self)
        self.fields['dedup_expression'].widget.attrs['placeholder'] = '$.issue.key'


class TriggerForm(forms.ModelForm):
    tag_name = forms.CharField(
        required=False,
        label='Trigger Tag',
        widget=forms.TextInput(attrs={'placeholder': 'Tag name…'}),
        help_text='Stamped on every ticket this trigger creates. Leave blank for none.',
    )

    class Meta:
        model = Trigger
        fields = ['name', 'source', 'filter', 'action', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.tag:
            self.initial['tag_name'] = self.instance.tag.name
        _apply_bootstrap(self)
