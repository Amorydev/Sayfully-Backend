from .base import *  # noqa: F403

DEBUG = True
REFRESH_COOKIE_SECURE = False          # http://localhost không có TLS
CORS_ALLOW_ALL_ORIGINS = True          # chỉ dev
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
ADS_ENABLED = True                     # bật để chạy thử luồng; prod đọc từ .env
ADS_SSV_REQUIRED = False               # không có callback của AdMob ở máy dev -> tin client
