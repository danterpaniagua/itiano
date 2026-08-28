from django.conf import settings


def app_version(request):
    return {'APP_VERSION': getattr(settings, 'APP_VERSION', 'dev')}


def notifications(request):
    if not request.user.is_authenticated:
        return {}
    from notifications.models import Notification
    qs = Notification.objects.filter(user=request.user)
    return {
        'unread_notifications_count': qs.filter(read_at__isnull=True).count(),
        'recent_notifications': qs[:8],
    }
