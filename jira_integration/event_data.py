"""Bulk, lightweight access to JiraEvent rows for MongoDB.

Event payloads are large JSON documents. Two MongoDB limits make the obvious code (one query per ticket, or
`order_by('received_at')` over many full documents) fail or crawl: every query is a network round trip, and an
in-memory sort is capped at 32 MB. `events_for` does ONE query that projects only the payload sub-paths the
caller needs and sorts in Python.
"""
from types import SimpleNamespace

from .models import JiraEvent


def _nest(target, parts, value):
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def events_for(ticket_ids, paths=(), newest_first=False):
    """Events of the given tickets, oldest first (or newest first), as light objects.

    Each object has `pk`, `ticket_id`, `event_type`, `received_at` and a partial `payload` dict holding only the
    requested `paths` (double-underscore notation, e.g. 'changelog__items', 'issue__fields__created'); paths that
    are missing in an event are simply absent from its payload, like `dict.get` would see them.
    """
    paths = list(paths)
    rows = JiraEvent.objects.filter(ticket_id__in=list(ticket_ids)).order_by().values_list(
        'pk', 'ticket_id', 'event_type', 'received_at', *[f'payload__{p}' for p in paths],
    )
    events = []
    for pk, ticket_id, event_type, received_at, *values in rows:
        payload = {}
        for path, value in zip(paths, values):
            if value is not None:
                _nest(payload, path.split('__'), value)
        events.append(SimpleNamespace(
            pk=pk, ticket_id=ticket_id, event_type=event_type, received_at=received_at, payload=payload,
        ))
    events.sort(key=lambda e: (e.received_at, str(e.pk)), reverse=newest_first)
    return events
