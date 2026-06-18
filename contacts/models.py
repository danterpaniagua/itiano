from django.contrib.auth.models import User
from django.db import models


class Contact(models.Model):
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    user = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='contact'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class ContactChannel(models.Model):
    TYPE_EMAIL = 'email'
    TYPE_POST = 'post'
    TYPE_PHONE = 'phone'
    TYPE_HANGOUTS = 'hangouts'
    TYPE_JIRA = 'jira'
    TYPE_TELEGRAM = 'telegram'
    TYPES = [
        (TYPE_EMAIL, 'Email'),
        (TYPE_POST, 'POST'),
        (TYPE_PHONE, 'Phone'),
        (TYPE_HANGOUTS, 'Hangouts'),
        (TYPE_JIRA, 'Jira'),
        (TYPE_TELEGRAM, 'Telegram'),
    ]

    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='channels')
    type = models.CharField(max_length=10, choices=TYPES)
    label = models.CharField(max_length=100, blank=True)
    value = models.CharField(max_length=500, blank=True, help_text='Email address or phone number')
    url = models.URLField(blank=True, help_text='POST endpoint URL')
    headers = models.JSONField(default=dict, blank=True, help_text='HTTP headers as key-value pairs')
    body = models.TextField(blank=True, help_text='Request body template. Use {{ ticket.id }}, {{ ticket.title }}, {{ ticket.state }}, {{ contact.first_name }}, {{ contact.last_name }}')
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ['-is_primary', 'type', 'label']

    def __str__(self):
        label = self.label or self.get_type_display()
        return f"{self.contact} — {label}"
