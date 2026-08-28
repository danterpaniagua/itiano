from django.contrib.auth.models import User
from django.db import models


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.CharField(max_length=500)
    url = models.CharField(max_length=500, blank=True)
    source = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} — {self.message}'


def notify(message, *, url='', source='', users=None, team=None):
    """Create a Notification for a single user, an iterable of users, or every
    current member of a core.Team (membership resolved now — a later change to
    team membership never retroactively adds/removes recipients of this call).

    Exactly one of `users`/`team` must be given. `users=[]` (or a team with no
    members) is a valid no-op, distinct from omitting both.
    """
    if (users is None) == (team is None):
        raise ValueError('notify() requires exactly one of users or team')

    if team is not None:
        recipients = list(team.members.all())
    elif isinstance(users, User):
        recipients = [users]
    else:
        recipients = list(users)

    if not recipients:
        return []

    return Notification.objects.bulk_create([
        Notification(user=recipient, message=message[:500], url=url, source=source)
        for recipient in recipients
    ])
