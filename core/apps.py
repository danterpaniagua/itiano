from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django_mongodb_backend.fields.ObjectIdAutoField'
    name = 'core'

    def ready(self):
        import core.signals  # noqa
