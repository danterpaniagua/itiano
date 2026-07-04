from django.contrib.auth.models import User
from django.db import models

from jira_integration.models import JiraTicket


class WorkSchedule(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='work_schedule')
    mon = models.BooleanField(default=True)
    tue = models.BooleanField(default=True)
    wed = models.BooleanField(default=True)
    thu = models.BooleanField(default=True)
    fri = models.BooleanField(default=True)
    sat = models.BooleanField(default=False)
    sun = models.BooleanField(default=False)
    start_time = models.TimeField(default='09:00')
    end_time = models.TimeField(default='18:00')
    jira_username = models.CharField(max_length=200, blank=True)
    timezone = models.CharField(max_length=64, default='America/Argentina/Cordoba')

    def __str__(self):
        return f"{self.user.username} schedule"

    @property
    def working_days(self):
        days = []
        for attr, label in [('mon','Mon'),('tue','Tue'),('wed','Wed'),('thu','Thu'),('fri','Fri'),('sat','Sat'),('sun','Sun')]:
            if getattr(self, attr):
                days.append(label)
        return days


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


class ReportProject(models.Model):
    tag_name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['tag_name']

    def __str__(self):
        return self.tag_name


class ReportService(models.Model):
    project = models.ForeignKey(ReportProject, on_delete=models.CASCADE, related_name='services')
    tag_name = models.CharField(max_length=100)

    class Meta:
        ordering = ['tag_name']
        unique_together = [('project', 'tag_name')]

    def __str__(self):
        return f"{self.project.tag_name} / {self.tag_name}"


class ReportEnvironment(models.Model):
    service = models.ForeignKey(ReportService, on_delete=models.CASCADE, related_name='environments')
    tag_name = models.CharField(max_length=100)

    class Meta:
        ordering = ['tag_name']
        unique_together = [('service', 'tag_name')]

    def __str__(self):
        return f"{self.service.tag_name} / {self.tag_name}"
