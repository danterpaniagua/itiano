from django.contrib.auth.models import User
from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name_plural = 'categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class Ticket(models.Model):
    TYPE_INCIDENT = 'incident'
    TYPE_SERVICE_REQUEST = 'service_request'
    TYPES = [
        (TYPE_INCIDENT, 'Incident'),
        (TYPE_SERVICE_REQUEST, 'Service Request'),
    ]

    STATE_NEW = 'new'
    STATE_ASSIGNED = 'assigned'
    STATE_IN_PROGRESS = 'in_progress'
    STATE_PENDING = 'pending'
    STATE_RESOLVED = 'resolved'
    STATE_CLOSED = 'closed'
    STATE_CANCELLED = 'cancelled'
    STATES = [
        (STATE_NEW, 'New'),
        (STATE_ASSIGNED, 'Assigned'),
        (STATE_IN_PROGRESS, 'In Progress'),
        (STATE_PENDING, 'Pending'),
        (STATE_RESOLVED, 'Resolved'),
        (STATE_CLOSED, 'Closed'),
        (STATE_CANCELLED, 'Cancelled'),
    ]

    PRIORITY_LOW = 'low'
    PRIORITY_MEDIUM = 'medium'
    PRIORITY_HIGH = 'high'
    PRIORITY_CRITICAL = 'critical'
    PRIORITIES = [
        (PRIORITY_LOW, 'Low'),
        (PRIORITY_MEDIUM, 'Medium'),
        (PRIORITY_HIGH, 'High'),
        (PRIORITY_CRITICAL, 'Critical'),
    ]

    STATE_BADGE = {
        STATE_NEW: 'primary',
        STATE_ASSIGNED: 'info',
        STATE_IN_PROGRESS: 'warning',
        STATE_PENDING: 'secondary',
        STATE_RESOLVED: 'success',
        STATE_CLOSED: 'dark',
        STATE_CANCELLED: 'danger',
    }

    title = models.CharField(max_length=255)
    description = models.TextField()
    type = models.CharField(max_length=20, choices=TYPES)
    state = models.CharField(max_length=20, choices=STATES, default=STATE_NEW)
    priority = models.CharField(max_length=20, choices=PRIORITIES, default=PRIORITY_MEDIUM)
    requester = models.ForeignKey(User, on_delete=models.PROTECT, related_name='tickets')
    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tickets'
    )
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True
    )
    service = models.CharField(max_length=255, blank=True)
    sub_service = models.CharField(max_length=255, blank=True)
    creator_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"#{self.pk} {self.title}"

    @property
    def state_badge_class(self):
        return self.STATE_BADGE.get(self.state, 'secondary')


class TicketEvent(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='events')
    actor = models.ForeignKey(User, on_delete=models.PROTECT)
    from_state = models.CharField(max_length=20, blank=True)
    to_state = models.CharField(max_length=20, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"#{self.ticket_id} {self.from_state} → {self.to_state}"


class Comment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.PROTECT)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.author} on #{self.ticket_id}"
