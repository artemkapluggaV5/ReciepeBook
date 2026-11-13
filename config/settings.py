from pathlib import Path
from urllib.parse import urlsplit
import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / '.env')
DEBUG = env('DEBUG')
SECRET_KEY = env('SECRET_KEY', default='development-only-change-before-deploy-8f5d2')
if not DEBUG and (SECRET_KEY.startswith('development-') or len(SECRET_KEY) < 50):
    raise ImproperlyConfigured('Set a random SECRET_KEY of at least 50 characters.')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1', '[::1]'])
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'core', 'products', 'orders', 'payments', 'delivery',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware', 'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware',
    'core.middleware.CanonicalHostMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.SecurityHeadersMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'],
              'APP_DIRS': True, 'OPTIONS': {'context_processors': [
                  'django.template.context_processors.request', 'django.contrib.auth.context_processors.auth',
                  'django.contrib.messages.context_processors.messages', 'core.context.site_context']}}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': env.db('DATABASE_URL', default=f'sqlite:///{(BASE_DIR / "development.sqlite3").as_posix()}')}
if not DEBUG and DATABASES['default']['ENGINE'] != 'django.db.backends.postgresql':
    raise ImproperlyConfigured('Production requires PostgreSQL DATABASE_URL.')
DATABASES['default']['CONN_MAX_AGE'] = 60
DATABASES['default']['CONN_HEALTH_CHECKS'] = True
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'ru'
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STORAGES = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
            'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'}}
# Public images are owner-managed. PDFs never use MEDIA_ROOT or MEDIA_URL.
MEDIA_ROOT = BASE_DIR / 'public-media'
MEDIA_URL = '/public-media/'
PRIVATE_ROOT = Path(env('PRIVATE_ROOT', default=str(BASE_DIR / 'private'))).resolve()
for public_directory in (MEDIA_ROOT, STATIC_ROOT, BASE_DIR / 'static'):
    public_directory = public_directory.resolve()
    if PRIVATE_ROOT == public_directory or public_directory in PRIVATE_ROOT.parents:
        raise ImproperlyConfigured('PRIVATE_ROOT must not be inside public media/static directories.')
SITE_URL = env('SITE_URL', default='http://127.0.0.1:8000').rstrip('/')
SITE_NAME = env('SITE_NAME', default='Новогодний сборник Маришкины рецепты')
if not DEBUG and (urlsplit(SITE_URL).scheme != 'https' or not urlsplit(SITE_URL).hostname):
    raise ImproperlyConfigured('Production SITE_URL must use https.')
# Canonical production address. Keep cookies host-only: link.* is delegated to
# an external service, so sharing the session cookie across subdomains is unsafe.
CANONICAL_HOST = ''
CANONICAL_REDIRECT_HOSTS = ()
if not DEBUG and urlsplit(SITE_URL).hostname in {'marishkinirecepti.ru', 'www.marishkinirecepti.ru'}:
    SITE_URL = 'https://www.marishkinirecepti.ru'
    CANONICAL_HOST = 'www.marishkinirecepti.ru'
    CANONICAL_REDIRECT_HOSTS = ('marishkinirecepti.ru',)
    for host in (*CANONICAL_REDIRECT_HOSTS, CANONICAL_HOST):
        if host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(host)
        origin = 'https://' + host
        if origin not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(origin)
CONTACT_EMAIL = env('CONTACT_EMAIL', default='marishkinirecepti@mail.ru')
if CONTACT_EMAIL.strip().lower() in {'marina.novikova-1976@mail.ru', 'marishkinirecepri@mail.ru'}:
    CONTACT_EMAIL = 'marishkinirecepti@mail.ru'
TELEGRAM_USERNAME = env('TELEGRAM_USERNAME', default='marisha_876').strip().lstrip('@')
TELEGRAM_SUPPORT_USERNAME = env('TELEGRAM_SUPPORT_USERNAME', default='novikov_valerii_s').strip().lstrip('@')
for username in (TELEGRAM_USERNAME, TELEGRAM_SUPPORT_USERNAME):
    if username and (not username.isascii() or not username.replace('_', '').isalnum() or not 5 <= len(username) <= 32):
        raise ImproperlyConfigured('Telegram settings must contain usernames, without URLs.')
MERCHANT_NAME = env('MERCHANT_NAME', default='[Имя или наименование продавца]')
MERCHANT_DETAILS = env('MERCHANT_DETAILS', default='[Статус, ИНН, адрес и юрисдикция продавца]')
MERCHANT_COUNTRY = env('MERCHANT_COUNTRY', default='')
SELLER_DISPLAY_NAME = env('SELLER_DISPLAY_NAME', default='ИП Новикова Марина Харлампиевна')
SELLER_INN = env('SELLER_INN', default='910620715151')
SELLER_OGRN = env('SELLER_OGRN', default='325237500301806')
LEGAL_VERSION = env('LEGAL_VERSION', default='draft-1')
SALES_ENABLED = env.bool('SALES_ENABLED', default=False)
LEGAL_READY = env.bool('LEGAL_READY', default=False)
FISCALIZATION_READY = env.bool('FISCALIZATION_READY', default=False)
PAYMENT_PROVIDER = 'yookassa'
YOOKASSA_SHOP_ID = env('YOOKASSA_SHOP_ID', default='')
YOOKASSA_SECRET_KEY = env('YOOKASSA_SECRET_KEY', default='')
YOOKASSA_TEST_MODE = env.bool('YOOKASSA_TEST_MODE', default=True)
# Live sales include receipts. Owner confirmed: YooKassa receipts, no VAT.
YOOKASSA_RECEIPTS_ENABLED = env.bool('YOOKASSA_RECEIPTS_ENABLED', default=False)
YOOKASSA_VAT_CODE = env.int('YOOKASSA_VAT_CODE', default=1)
DOWNLOAD_DAYS = env.int('DOWNLOAD_DAYS', default=30)
DOWNLOAD_LIMIT = env.int('DOWNLOAD_LIMIT', default=20)
# Outbound email is disabled, including stale SMTP/API values in an existing .env.
EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'
SESSION_COOKIE_AGE = max(30, DOWNLOAD_DAYS) * 86400
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_REDIRECT_EXEMPT = [r'^health/$']
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
CSRF_FAILURE_VIEW = 'core.views.csrf_failure'
X_FRAME_OPTIONS = 'DENY'
TRUST_PROXY = env.bool('TRUST_PROXY', default=False)
if TRUST_PROXY:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
DATA_UPLOAD_MAX_MEMORY_SIZE = 65536
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
LOGGING = {'version': 1, 'disable_existing_loggers': False,
           'filters': {'payment_privacy': {'()': 'core.logging.PaymentPrivacyFilter'}},
           'formatters': {'safe': {'format': '{levelname} {name} {message}', 'style': '{'}},
           'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'safe', 'filters': ['payment_privacy']}},
           'root': {'handlers': ['console'], 'level': 'INFO'},
           'loggers': {'django.server': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
                       'django.request': {'handlers': ['console'], 'level': 'CRITICAL', 'propagate': False}}}
