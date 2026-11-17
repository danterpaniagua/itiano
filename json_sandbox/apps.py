from django.apps import AppConfig


class JsonSandboxConfig(AppConfig):
    default_auto_field = 'django_mongodb_backend.fields.ObjectIdAutoField'
    name = 'json_sandbox'
