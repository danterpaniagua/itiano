from django.contrib.auth.models import User
from django.db import models


class Action(models.Model):
    ACTION_CREATE_TICKET = 'create_ticket'
    ACTION_TYPES = [
        (ACTION_CREATE_TICKET, 'Create Ticket'),
    ]

    FORMAT_RAW = 'raw'
    FORMAT_HTML = 'html'
    FORMAT_MARKDOWN = 'markdown'
    FORMAT_JIRA_WIKI = 'jira_wiki'
    DESCRIPTION_FORMATS = [
        (FORMAT_RAW, 'Plain text'),
        (FORMAT_HTML, 'HTML'),
        (FORMAT_MARKDOWN, 'Markdown'),
        (FORMAT_JIRA_WIKI, 'Jira Wiki Markup'),
    ]

    name = models.CharField(max_length=100)
    action_type = models.CharField(max_length=50, choices=ACTION_TYPES)
    description_format = models.CharField(
        max_length=10,
        choices=DESCRIPTION_FORMATS,
        default=FORMAT_RAW,
        help_text='Format of the description field in the incoming payload.',
    )
    field_mappings = models.JSONField(
        help_text=(
            'Map ticket fields to JSONPath expressions or literal values. '
            'Supported keys: key, title, description, type, priority, category, creator, service, sub_service. '
            'Example: {"key": "$.issue.key", "title": "$.issue.fields.summary", '
            '"description": "$.issue.fields.description", "type": "incident", "priority": "medium"}'
        )
    )
    system_user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        help_text='User set as requester for tickets created by this action.',
    )
    tag_expressions = models.JSONField(
        default=list,
        blank=True,
        help_text='List of {expression, color} objects. Each resolved value becomes a colored tag on the ticket.',
    )
    dedup_expression = models.CharField(
        max_length=500,
        blank=True,
        help_text='JSONPath to extract a unique key from the payload (e.g. $.issue.key). If set, an existing ticket with that key is updated instead of creating a new one.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ActionHistory(models.Model):
    action = models.ForeignKey(Action, on_delete=models.CASCADE, related_name='history')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    field_name = models.CharField(max_length=100)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']


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


class TriggerHistory(models.Model):
    trigger = models.ForeignKey(Trigger, on_delete=models.CASCADE, related_name='history')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    field_name = models.CharField(max_length=100)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']


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
