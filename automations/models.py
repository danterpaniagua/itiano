from django.contrib.auth.models import User
from django.db import models


class Action(models.Model):
    ACTION_CREATE_TICKET = 'create_ticket'
    ACTION_TYPES = [
        (ACTION_CREATE_TICKET, 'Create Ticket'),
    ]

    name = models.CharField(max_length=100)
    action_type = models.CharField(max_length=50, choices=ACTION_TYPES)
    field_mappings = models.JSONField(
        help_text=(
            'Map ticket fields to JSONPath expressions or literal values. '
            'Example: {"title": "$.issue.key", "description": "$.issue.fields.description", '
            '"type": "incident", "priority": "medium", "category": "Automation"}'
        )
    )
    system_user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        help_text='User set as requester for tickets created by this action.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Trigger(models.Model):
    SOURCE_JIRA = 'jira'
    SOURCES = [
        (SOURCE_JIRA, 'Jira'),
    ]

    name = models.CharField(max_length=100)
    source = models.CharField(max_length=50, choices=SOURCES)
    filter = models.JSONField(
        help_text=(
            'Structured filter condition tree. '
            'Example: {"and": [{"path": "$.issue.fields.project.name", "op": "eq", "value": "GIT"}, '
            '{"path": "$.issue.labels", "op": "in", "value": ["Azure", "PROD"]}]}'
        )
    )
    action = models.ForeignKey(Action, on_delete=models.CASCADE, related_name='triggers')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class TriggerLog(models.Model):
    RESULT_MATCHED = 'matched'
    RESULT_SKIPPED = 'skipped'
    RESULT_ERROR = 'error'
    RESULTS = [
        (RESULT_MATCHED, 'Matched'),
        (RESULT_SKIPPED, 'Skipped'),
        (RESULT_ERROR, 'Error'),
    ]

    trigger = models.ForeignKey(Trigger, on_delete=models.CASCADE, related_name='logs')
    action = models.ForeignKey(Action, on_delete=models.SET_NULL, null=True, related_name='logs')
    payload_snapshot = models.JSONField()
    result = models.CharField(max_length=10, choices=RESULTS)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.trigger} → {self.result}"
