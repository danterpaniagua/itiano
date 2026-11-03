"""`@` mentions in notes (v5.18.7): parser, per-viewer resolver, search and backlinks.

Tokens: `@GITIN-2315` (Jira ticket), `@ticket:42` (ITSM ticket), `@cred:17` (credential).
Only these strict tokens count; `user@host.com` and anything in code is ignored.
Nothing here ever reads a secret: a credential resolves to its name, type and page link.
"""
import html
import re

from django.db.models import Q
from django.urls import reverse

from .models import Note, NoteMention

TOKEN_RE = re.compile(r'(?<![\w@])@(?:(ticket|cred):(\d+)|([A-Z][A-Z0-9]+-\d+))(?![\w-])')
FENCE_RE = re.compile(r'^ {0,3}(`{3,}|~{3,})')
INLINE_CODE_RE = re.compile(r'(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)')
KEY_PREFIX_RE = re.compile(r'^[A-Za-z][A-Za-z0-9]*-\d*$')

MIN_QUERY = 2
MAX_PER_KIND = 8

CRED_ICONS = {
    'password': 'bi-key',
    'ssh_key': 'bi-terminal',
    'certificate': 'bi-patch-check',
    'api_key': 'bi-braces',
    'secret': 'bi-shield-lock',
}


def _blank(text):
    return re.sub(r'[^\r\n]', ' ', text)


def _mask_code(text):
    """Same text with fenced blocks and inline code blanked, so offsets still match the original."""
    out = []
    fence = None
    for line in text.splitlines(keepends=True):
        match = FENCE_RE.match(line)
        if fence is None:
            if match:
                fence = (match.group(1)[0], len(match.group(1)))
                out.append(_blank(line))
            else:
                out.append(INLINE_CODE_RE.sub(lambda m: _blank(m.group(0)), line))
        else:
            out.append(_blank(line))
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= fence[1] \
                    and line.strip() == match.group(1):
                fence = None
    return ''.join(out)


def find_mentions(body):
    """-> [(start, end, kind, ref)] for every token outside code, in order."""
    found = []
    for match in TOKEN_RE.finditer(_mask_code(body or '')):
        if match.group(3):
            found.append((match.start(), match.end(), NoteMention.KIND_JIRA, match.group(3)))
        else:
            found.append((match.start(), match.end(), match.group(1), str(int(match.group(2)))))
    return found


def parse_mentions(body):
    """Unique (kind, ref) pairs, in order of first appearance."""
    seen = []
    for _, _, kind, ref in find_mentions(body):
        if (kind, ref) not in seen:
            seen.append((kind, ref))
    return seen


def sync_mentions(note):
    """Replace the note's mentions with the set found in its body."""
    wanted = parse_mentions(note.body)
    note.mentions.all().delete()
    NoteMention.objects.bulk_create([NoteMention(note=note, kind=k, ref=r) for k, r in wanted])


# ── Resolution, always for the viewer ────────────────────────────────────────

def _visible_tickets(user):
    from itsm.models import Ticket
    from itsm.permissions import get_role
    role = get_role(user)
    if role in ('agent', 'manager', 'admin'):
        return Ticket.objects.all()
    if role == 'requester':
        return Ticket.objects.filter(requester=user)
    return Ticket.objects.none()


def resolve(user, kind, ref):
    """-> {'state': ok|no_access|deleted|not_found, 'label', 'url', 'icon'}. No name or title unless the viewer may see it."""
    token = f'@{ref}' if kind == NoteMention.KIND_JIRA else f'@{kind}:{ref}'
    if kind == NoteMention.KIND_JIRA:
        from jira_integration.models import JiraTicket
        ticket = JiraTicket.objects.filter(issue_key=ref).first()
        if ticket is None:
            return {'state': 'not_found', 'label': f'{token} (not found)', 'url': '', 'icon': 'bi-question-circle'}
        if ticket.is_deleted:
            return {'state': 'deleted', 'label': f'{token} (deleted)', 'url': '', 'icon': 'bi-trash'}
        label = f'{ticket.issue_key} · {ticket.title}' if ticket.title else ticket.issue_key
        return {'state': 'ok', 'label': label, 'url': reverse('jira-ticket-detail', args=[ticket.issue_key]), 'icon': 'bi-bug'}

    if kind == NoteMention.KIND_TICKET:
        from itsm.models import Ticket
        from itsm.permissions import can_view_ticket
        ticket = Ticket.objects.filter(pk=int(ref)).first()
        if ticket is None:
            return {'state': 'not_found', 'label': f'{token} (not found)', 'url': '', 'icon': 'bi-question-circle'}
        if not can_view_ticket(user, ticket):
            return {'state': 'no_access', 'label': 'ticket (no access)', 'url': '', 'icon': 'bi-lock'}
        return {'state': 'ok', 'label': f'#{ticket.pk} · {ticket.title}', 'url': reverse('ticket-detail', args=[ticket.pk]), 'icon': 'bi-ticket-detailed'}

    from vault.models import Credential
    from vault.views import _can_access
    credential = Credential.objects.select_related('container').filter(pk=int(ref)).first()
    if credential is None:
        return {'state': 'not_found', 'label': f'{token} (not found)', 'url': '', 'icon': 'bi-question-circle'}
    if not _can_access(user, credential):
        return {'state': 'no_access', 'label': 'credential (no access)', 'url': '', 'icon': 'bi-lock'}
    if credential.is_deleted:
        return {'state': 'deleted', 'label': f'{token} (deleted)', 'url': '', 'icon': 'bi-trash'}
    return {
        'state': 'ok', 'label': credential.name, 'url': reverse('vault-detail', args=[credential.pk]),
        'icon': CRED_ICONS.get(credential.credential_type, 'bi-key'),
    }


def _md_safe(text):
    """Escape for inline HTML that goes through marked: HTML plus the Markdown characters."""
    return re.sub(r'[\\`*_\[\]~|]', lambda m: f'&#{ord(m.group())};', html.escape(text))


def _chip(info):
    label = _md_safe(info['label'])
    if info['state'] == 'ok':
        return (f'<a href="{html.escape(info["url"])}" class="badge text-bg-light border text-decoration-none fw-normal">'
                f'<i class="bi {info["icon"]}"></i> {label}</a>')
    return f'<span class="badge text-bg-secondary fw-normal"><i class="bi {info["icon"]}"></i> {label}</span>'


def render_mentions(user, body):
    """The Markdown body with every mention outside code replaced by a chip for this viewer."""
    cache = {}
    out = []
    last = 0
    for start, end, kind, ref in find_mentions(body):
        if (kind, ref) not in cache:
            cache[(kind, ref)] = resolve(user, kind, ref)
        out.append(body[last:start])
        out.append(_chip(cache[(kind, ref)]))
        last = end
    out.append(body[last:])
    return ''.join(out)


# ── Autocomplete ─────────────────────────────────────────────────────────────

def search(user, query):
    """Objects the user can see that match what follows the `@`. At most MAX_PER_KIND per kind."""
    from jira_integration.models import JiraTicket
    from vault.views import _container_path, _visible_credentials

    query = (query or '').strip()
    prefixed = re.match(r'^(ticket|cred):(.*)$', query, re.I)
    only = prefixed.group(1).lower() if prefixed else None
    term = prefixed.group(2).strip() if prefixed else query
    if only is None and len(term) < MIN_QUERY:   # a `ticket:` / `cred:` prefix lists right away
        return []

    want_jira = only is None
    want_ticket = only in (None, NoteMention.KIND_TICKET) and not KEY_PREFIX_RE.match(query)
    want_cred = only in (None, NoteMention.KIND_CRED) and not KEY_PREFIX_RE.match(query)
    results = []

    if want_jira:
        jira = JiraTicket.objects.filter(is_deleted=False)
        if KEY_PREFIX_RE.match(query):
            jira = jira.filter(issue_key__istartswith=query)
        else:
            jira = jira.filter(Q(title__icontains=term) | Q(issue_key__icontains=term))
        for ticket in jira.order_by('issue_key')[:MAX_PER_KIND]:
            results.append({'kind': 'jira', 'token': f'@{ticket.issue_key}', 'icon': 'bi-bug',
                            'label': f'{ticket.issue_key} · {ticket.title}' if ticket.title else ticket.issue_key})
    if want_ticket:
        tickets = _visible_tickets(user)
        tickets = tickets.filter(Q(title__icontains=term) | Q(pk=int(term))) if term.isdigit() \
            else tickets.filter(title__icontains=term)
        for ticket in tickets.order_by('-pk')[:MAX_PER_KIND]:
            results.append({'kind': 'ticket', 'token': f'@ticket:{ticket.pk}', 'icon': 'bi-ticket-detailed',
                            'label': f'#{ticket.pk} · {ticket.title}'})
    if want_cred:
        credentials = _visible_credentials(user).select_related('container')
        match = Q(name__icontains=term) | Q(tags__name__icontains=term)
        credentials = credentials.filter(match | Q(pk=int(term))) if term.isdigit() else credentials.filter(match)
        for credential in credentials.order_by('name')[:MAX_PER_KIND]:
            results.append({'kind': 'cred', 'token': f'@cred:{credential.pk}',
                            'icon': CRED_ICONS.get(credential.credential_type, 'bi-key'),
                            'label': credential.name,
                            'sub': _container_path(credential.container) if credential.container_id else 'Personal',
                            'tags': [tag.name for tag in credential.tags.all()]})
    return results


# ── Backlinks ────────────────────────────────────────────────────────────────

def backlinks(user, kind, ref):
    """Notes mentioning the object that the viewer can read (owner or shared with them)."""
    return list(
        Note.objects.filter(mentions__kind=kind, mentions__ref=str(ref))
        .filter(Q(owner=user) | Q(shares__shared_with=user))
        .select_related('owner').distinct().order_by('-updated_at')
    )
