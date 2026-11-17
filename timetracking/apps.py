from django.apps import AppConfig


class TimetrackingConfig(AppConfig):
    default_auto_field = 'django_mongodb_backend.fields.ObjectIdAutoField'
    name = 'timetracking'
    verbose_name = 'Time Tracking'

    def ready(self):
        from notes import system_prompts
        from . import tag_report
        system_prompts.register(tag_report.PROMPT_ID, 'itiano', 'Time report prompt', tag_report.PROMPT_DEFAULT)
