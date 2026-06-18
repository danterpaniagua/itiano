import zoneinfo

from django.utils import timezone


class TimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            try:
                from timetracking.models import WorkSchedule
                schedule = WorkSchedule.objects.filter(user=request.user).select_related().first()
                if schedule and schedule.timezone:
                    timezone.activate(zoneinfo.ZoneInfo(schedule.timezone))
                else:
                    timezone.deactivate()
            except Exception:
                timezone.deactivate()
        else:
            timezone.deactivate()
        response = self.get_response(request)
        timezone.deactivate()
        return response
