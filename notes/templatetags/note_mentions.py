from django import template

from notes.mentions import backlinks

register = template.Library()


@register.inclusion_tag('notes/_backlinks.html')
def note_backlinks(user, kind, ref):
    """Collapsed "Notes mentioning this" card; renders nothing when the viewer can read none."""
    return {'notes': backlinks(user, kind, ref), 'viewer': user, 'uid': f'{kind}-{ref}'.replace(':', '-').replace('.', '-')}
