from django.apps import AppConfig


class SettingsHubConfig(AppConfig):
    default_auto_field = 'django_mongodb_backend.fields.ObjectIdAutoField'
    name = 'settings_hub'
    verbose_name = 'Settings Hub'
