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
