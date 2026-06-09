from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('tickets/', include('itsm.urls')),
    path('jira/', include('jira_integration.urls')),
    path('sandbox/', include('json_sandbox.urls')),
    path('automations/', include('automations.urls')),
    path('clipboard/', include('clipboard.urls')),
    path('vault/', include('vault.urls')),
    path('', include('core.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
