from django.apps import AppConfig


class VaultConfig(AppConfig):
    default_auto_field = 'django_mongodb_backend.fields.ObjectIdAutoField'
    name = 'vault'

    def ready(self):
        import vault.signals  # noqa: F401
