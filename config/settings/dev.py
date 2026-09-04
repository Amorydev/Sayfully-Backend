from .base import *  # noqa: F403

DEBUG = True
REFRESH_COOKIE_SECURE = False          # http://localhost không có TLS
CORS_ALLOW_ALL_ORIGINS = True          # chỉ dev
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
