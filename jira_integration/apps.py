from django.apps import AppConfig


class JiraIntegrationConfig(AppConfig):
    default_auto_field = 'django_mongodb_backend.fields.ObjectIdAutoField'
    name = 'jira_integration'
