from django.apps import AppConfig


class ItsmConfig(AppConfig):
    default_auto_field = 'django_mongodb_backend.fields.ObjectIdAutoField'
    name = 'itsm'
