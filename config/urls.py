from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('tickets/', include('itsm.urls')),
    path('jira/', include('jira_integration.urls')),
    path('sandbox/', include('json_sandbox.urls')),
    path('', include('core.urls')),
]
