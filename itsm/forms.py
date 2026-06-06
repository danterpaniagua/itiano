from django import forms

from .models import Comment, Ticket


class BootstrapFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault('class', 'form-select')
            else:
                widget.attrs.setdefault('class', 'form-control')


class TicketForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ['title', 'type', 'priority', 'category', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
        }


class CommentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['body']
        widgets = {
            'body': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Add a comment...'}),
        }
        labels = {'body': ''}
