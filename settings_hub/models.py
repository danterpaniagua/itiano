from django.db import models


class AppSetting(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['key']
        verbose_name = 'App Setting'
        verbose_name_plural = 'App Settings'

    def __str__(self):
        return f'{self.key} = {self.value}'


def get_app_setting(key, default=''):
    try:
        return AppSetting.objects.get(key=key).value
    except AppSetting.DoesNotExist:
        return default


class JiraStatusConfig(models.Model):
    CATEGORY_CHOICES = [
        ('in_progress', 'In Progress'),
        ('blocked',     'Blocked'),
        ('done',        'Done'),
        ('testing',     'Testing'),
        ('backlog',     'Backlog'),
        ('other',       'Other'),
    ]

    status_name = models.CharField(max_length=100, unique=True)
    category    = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='other')
    is_terminal = models.BooleanField(default=False, verbose_name='Closed Status')

    class Meta:
        ordering = ['category', 'status_name']
        verbose_name = 'Jira Status Config'
        verbose_name_plural = 'Jira Status Configs'

    def __str__(self):
        return f'{self.status_name} ({self.get_category_display()})'
