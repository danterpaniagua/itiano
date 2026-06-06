from django.db import transaction

TRANSITIONS = {
    'new': {
        'assigned': ['agent', 'manager', 'admin'],
        'cancelled': ['requester', 'manager', 'admin'],
    },
    'assigned': {
        'in_progress': ['agent', 'manager', 'admin'],
        'pending': ['agent', 'manager', 'admin'],
        'cancelled': ['manager', 'admin'],
    },
    'in_progress': {
        'pending': ['agent', 'manager', 'admin'],
        'resolved': ['agent', 'manager', 'admin'],
        'cancelled': ['manager', 'admin'],
    },
    'pending': {
        'in_progress': ['agent', 'manager', 'admin'],
        'cancelled': ['manager', 'admin'],
    },
    'resolved': {
        'closed': ['requester', 'manager', 'admin'],
        'in_progress': ['requester', 'agent', 'manager', 'admin'],
    },
    'closed': {},
    'cancelled': {},
}

TRANSITION_LABELS = {
    'assigned': 'Assign',
    'in_progress': 'Start Work',
    'pending': 'Set Pending',
    'resolved': 'Mark Resolved',
    'closed': 'Close',
    'cancelled': 'Cancel',
}


def get_available_transitions(ticket, user):
    try:
        role = user.userprofile.role
    except Exception:
        return []

    current = ticket.state
    available = []

    for to_state, allowed_roles in TRANSITIONS.get(current, {}).items():
        if role not in allowed_roles:
            continue
        if role == 'requester' and ticket.requester_id != user.pk:
            continue
        if role == 'agent' and current != 'new' and ticket.assigned_to_id != user.pk:
            continue
        available.append(to_state)

    return available


@transaction.atomic
def perform_transition(ticket, to_state, actor, note=''):
    from .models import TicketEvent

    available = get_available_transitions(ticket, actor)
    if to_state not in available:
        raise PermissionError(f"Transition to '{to_state}' is not allowed.")

    from_state = ticket.state

    if from_state == 'new' and to_state == 'assigned' and ticket.assigned_to is None:
        ticket.assigned_to = actor

    ticket.state = to_state
    ticket.save(update_fields=['state', 'assigned_to', 'updated_at'])

    TicketEvent.objects.create(
        ticket=ticket,
        actor=actor,
        from_state=from_state,
        to_state=to_state,
        note=note,
    )
