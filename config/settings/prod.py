import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

from .base import *  # noqa: F403
from .base import env

DEBUG = False

SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^health/$"]  # healthcheck trong container gọi HTTP thẳng gunicorn
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# Cache dùng chung giữa các process gunicorn + worker (locmem chỉ sống trong 1 process): rate-limit đếm đúng,
# preview/caption YouTube cache được cho import. Bảng tạo bằng `manage.py createcachetable` (scripts/deploy.sh).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
        "TIMEOUT": 3600,
        "OPTIONS": {"MAX_ENTRIES": 20000, "CULL_FREQUENCY": 4},
    }
}

if env("SENTRY_DSN", default=""):
    sentry_sdk.init(
        dsn=env("SENTRY_DSN"),
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,  # không gửi PII
    )
