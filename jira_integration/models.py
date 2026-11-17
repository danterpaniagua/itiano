from django.db import models
from django.utils import timezone


class JiraTicket(models.Model):
    issue_key = models.CharField(max_length=50, unique=True)
    title = models.CharField(max_length=500, blank=True)
    project_key = models.CharField(max_length=50, blank=True)
    issue_type = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=100, blank=True)
    assignee            = models.CharField(max_length=200, blank=True)
    assignee_account_id = models.CharField(max_length=100, blank=True)
    labels = models.JSONField(default=list, blank=True)
    parent_key = models.CharField(max_length=50, blank=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # MongoDB sorts without an index are capped at 32 MB (documents carry large JSON payloads).
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['updated_at'], name='jira_ticket_updated_idx')]

    def __str__(self):
        return self.issue_key


class JiraEvent(models.Model):
    ticket = models.ForeignKey(JiraTicket, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=100, blank=True)
    summary = models.CharField(max_length=500, blank=True)
    payload = models.JSONField()
    received_at = models.DateTimeField(default=timezone.now)

    class Meta:
        # MongoDB sorts without an index are capped at 32 MB (documents carry large JSON payloads).
        ordering = ['received_at']
        indexes = [models.Index(fields=['received_at'], name='jira_event_received_idx')]

    def __str__(self):
        return f"{self.ticket.issue_key} — {self.event_type}"
