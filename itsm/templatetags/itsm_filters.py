import re

from django import template
from django.utils.html import escape, mark_safe

register = template.Library()

_HTML_RE = re.compile(r'</?[a-z][a-z0-9]*[\s/>]', re.IGNORECASE)


@register.filter
def render_description(value):
    if not value:
        return ''
    if _HTML_RE.search(value):
        return mark_safe(value)
    return mark_safe(escape(value).replace('\n', '<br>'))
