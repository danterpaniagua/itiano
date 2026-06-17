from django.contrib.auth.models import User
from django.db import models

from jira_integration.models import JiraTicket


class TimeEntry(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='time_entries')
    jira_ticket = models.ForeignKey(JiraTicket, on_delete=models.CASCADE, related_name='time_entries')
    date = models.DateField()
    minutes = models.PositiveIntegerField()
    activity = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.user.username} — {self.jira_ticket.issue_key} — {self.date}"

    @property
    def hours_display(self):
        h, m = divmod(self.minutes, 60)
        if h and m:
            return f"{h}h {m}m"
        if h:
            return f"{h}h"
        return f"{m}m"
