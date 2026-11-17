from django.urls import register_converter
from django.contrib.admin.apps import AdminConfig
from django.contrib.auth.apps import AuthConfig
from django.contrib.contenttypes.apps import ContentTypesConfig


class MongoAdminConfig(AdminConfig):
    default_auto_field = 'django_mongodb_backend.fields.ObjectIdAutoField'


class MongoAuthConfig(AuthConfig):
    default_auto_field = 'django_mongodb_backend.fields.ObjectIdAutoField'


class MongoContentTypesConfig(ContentTypesConfig):
    default_auto_field = 'django_mongodb_backend.fields.ObjectIdAutoField'


class ObjectIdConverter:
    """URL converter for MongoDB ObjectId primary keys (24 hex characters)."""

    regex = '[0-9a-fA-F]{24}'

    def to_python(self, value):
        return value

    def to_url(self, value):
        return str(value)


register_converter(ObjectIdConverter, 'oid')
