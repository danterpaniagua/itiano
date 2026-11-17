import os
from pathlib import Path

from django_mongodb_backend import parse_uri

BASE_DIR = Path(__file__).resolve().parent.parent

_version_file = BASE_DIR / 'VERSION'
APP_VERSION = _version_file.read_text().strip() if _version_file.exists() else 'dev'

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-placeholder')
DEBUG = os.environ.get('DEBUG', 'False') == 'True'
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

INSTALLED_APPS = [
    'config.apps.MongoAdminConfig',
    'config.apps.MongoAuthConfig',
    'config.apps.MongoContentTypesConfig',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
    'itsm',
    'jira_integration',
    'json_sandbox',
    'automations',
    'clipboard',
    'vault',
    'notes',
    'contacts',
    'settings_hub',
    'timetracking',
    'notifications',
]

if DEBUG:
    INSTALLED_APPS.append('django_extensions')

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.middleware.TimezoneMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.app_version',
                'core.context_processors.notifications',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

def _env(name, default=''):
    # docker --env-file keeps surrounding quotes; strip them so quoted .env values work everywhere.
    return os.environ.get(name, default).strip().strip('"').strip("'")


_mongo_uri = _env('MONGODB_URI')

DATABASES = {
    'default': parse_uri(_mongo_uri, db_name=_env('MONGODB_DB', 'itiano')),
}

# Credentials not embedded in the URI (e.g. MONGODB_USERNAME / MONGODB_PASSWORD in .env).
if _env('MONGODB_USERNAME') and '@' not in _mongo_uri.split('://', 1)[-1].split('/', 1)[0]:
    DATABASES['default']['USER'] = _env('MONGODB_USERNAME')
    DATABASES['default']['PASSWORD'] = _env('MONGODB_PASSWORD')

TEST_RUNNER = 'config.test_runner.MongoDiscoverRunner'

DATABASE_ROUTERS = ['django_mongodb_backend.routers.MongoRouter']

MIGRATION_MODULES = {
    'admin': 'mongo_migrations.admin',
    'auth': 'mongo_migrations.auth',
    'contenttypes': 'mongo_migrations.contenttypes',
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
MAX_UPLOAD_SIZE = 10 * 1024 * 1024

DEFAULT_AUTO_FIELD = 'django_mongodb_backend.fields.ObjectIdAutoField'

JIRA_WEBHOOK_SECRET = os.environ.get('JIRA_WEBHOOK_SECRET', '')

JIRA_API_BASE_URL = os.environ.get('JIRA_API_BASE_URL', '')
JIRA_API_EMAIL = os.environ.get('JIRA_API_EMAIL', '')
JIRA_API_TOKEN = os.environ.get('JIRA_API_TOKEN', '')

LOGIN_REDIRECT_URL = '/'
LOGIN_URL = '/accounts/login/'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            '()': 'config.logging_formatters.ExtraFormatter',
            'format': '{asctime} {levelname} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'app.log',
            'formatter': 'standard',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
}
