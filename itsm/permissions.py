def get_role(user):
    try:
        return user.userprofile.role
    except Exception:
        return None


def can_view_ticket(user, ticket):
    role = get_role(user)
    if role in ('agent', 'manager', 'admin'):
        return True
    return role == 'requester' and ticket.requester_id == user.pk


def can_comment(user, ticket):
    role = get_role(user)
    if role in ('manager', 'admin'):
        return True
    if role == 'agent':
        return ticket.assigned_to_id == user.pk
    return role == 'requester' and ticket.requester_id == user.pk
