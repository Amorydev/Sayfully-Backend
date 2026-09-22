"""Cấu hình dùng chung. Không đặt secret ở đây — đọc từ .env."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, []),
    ACCESS_TOKEN_MINUTES=(int, 30),
    REFRESH_TOKEN_DAYS=(int, 60),
    AI_ENABLED=(bool, False),
    AI_FREE_TURNS=(int, 20),
    AI_PREMIUM_TURNS=(int, 200),
    VIDEO_IMPORT_ENABLED=(bool, True),
    VIDEO_IMPORT_MAX_SEC=(int, 1200),
    VIDEO_IMPORT_DAILY_LIMIT=(int, 5),
    VIDEO_IMPORT_SYNC=(bool, False),
    AI_TIMEOUT=(int, 30),
    PLAY_INTEGRITY_MAX_AGE_SEC=(int, 600),
    REVENUECAT_WEBHOOK_SECRET=(str, ""),
    REVENUECAT_API_KEY=(str, ""),
    PAYOS_WEBHOOK_SECRET=(str, ""),
    PAYOS_API_KEY=(str, ""),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# ---------------------------------------------------------------- apps
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",  # ArrayField, trigram, GIN
]
THIRD_PARTY_APPS = [
    "corsheaders",
    "django_q",
]
LOCAL_APPS = [
    "apps.common",
    "apps.accounts",
    "apps.content",
    "apps.learning",
    "apps.exams",
    "apps.gamification",
    "apps.billing",
    "apps.ai",
    "apps.notifications",
    "apps.blog",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "apps.common.middleware.ApiErrorEnvelopeMiddleware",  # ngoài cùng: bọc lỗi không qua Ninja
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # static (admin, Swagger) do gunicorn tự phục vụ
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------- database
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = False  # tự quản transaction ở service
DATABASES["default"]["CONN_MAX_AGE"] = 60
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------- auth
AUTH_USER_MODEL = "accounts.User"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",  # mạnh hơn PBKDF2
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
PASSWORD_RESET_TIMEOUT = 30 * 60  # token đặt lại mật khẩu sống 30 phút

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- JWT (tự quản, không dùng thư viện ngoài) ---
JWT_SIGNING_KEY = env("JWT_SIGNING_KEY", default=SECRET_KEY)
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = env("ACCESS_TOKEN_MINUTES")
REFRESH_TOKEN_DAYS = env("REFRESH_TOKEN_DAYS")

# --- Cookie cho web (Next.js). Mobile dùng Bearer header. ---
REFRESH_COOKIE_NAME = "sayfully_rt"
REFRESH_COOKIE_PATH = "/api/v1/auth"
REFRESH_COOKIE_SECURE = True  # dev.py hạ xuống False
REFRESH_COOKIE_SAMESITE = "Lax"
REFRESH_COOKIE_DOMAIN = None

# --- Social ---
GOOGLE_CLIENT_IDS = [
    cid
    for cid in [
        env("GOOGLE_CLIENT_ID_ANDROID", default=""),
        env("GOOGLE_CLIENT_ID_IOS", default=""),
        env("GOOGLE_CLIENT_ID_WEB", default=""),
    ]
    if cid
]
APPLE_AUDIENCES = [
    aud
    for aud in [
        env("APPLE_BUNDLE_ID", default=""),
        env("APPLE_SERVICE_ID", default=""),
    ]
    if aud
]

# ---------------------------------------------------------------- CORS / CSRF
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True  # bắt buộc để web gửi cookie
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS

# ---------------------------------------------------------------- storage (R2)
R2_ACCOUNT_ID = env("R2_ACCOUNT_ID", default="")
R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID", default="")
R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY", default="")
R2_BUCKET = env("R2_BUCKET", default="sayfully-media")
R2_PUBLIC_BASE = env("R2_PUBLIC_BASE", default="")  # ghép URL đầy đủ khi trả API

# ---------------------------------------------------------------- misc
RESEND_API_KEY = env("RESEND_API_KEY", default="")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Sayfully <no-reply@sayfully.com>")
# Trang đặt lại mật khẩu ở phía frontend (Next.js)
PASSWORD_RESET_URL = env("PASSWORD_RESET_URL", default="http://localhost:3000/reset-password")

# Chỉ dùng trong pipeline nội dung, không gọi khi người học bật nút Dịch.
GOOGLE_TRANSLATE_API_KEY = env("GOOGLE_TRANSLATE_API_KEY", default="")

AI_ENABLED = env("AI_ENABLED")
# Gia sư AI: provider `openai_compat` gọi endpoint chat/completions tương thích OpenAI
# (DeepSeek trực tiếp hoặc qua OpenRouter); `mock` trả lời mẫu để dựng UI không cần key.
AI_PROVIDER = env("AI_PROVIDER", default="mock")
AI_BASE_URL = env("AI_BASE_URL", default="https://openrouter.ai/api/v1")
AI_MODEL = env("AI_MODEL", default="deepseek/deepseek-v4-flash")
# Model thử lại một lần khi AI_MODEL lỗi mạng/timeout/429/5xx; để trống = không dự phòng.
AI_FALLBACK_MODEL = env("AI_FALLBACK_MODEL", default="")
AI_API_KEY = env("AI_API_KEY", default="")
AI_TIMEOUT = env("AI_TIMEOUT")
# Provider riêng cho xử lý VIDEO (dịch phụ đề, ước lượng CEFR) — tách khỏi gia sư AI để chọn model rẻ/ngữ cảnh
# dài và không tranh hạn mức với hội thoại. Trống → dùng lại AI_* ở trên (ghép lúc gọi, xem apps.ai.llm.profile).
VIDEO_AI_PROVIDER = env("VIDEO_AI_PROVIDER", default="")
VIDEO_AI_BASE_URL = env("VIDEO_AI_BASE_URL", default="")
VIDEO_AI_MODEL = env("VIDEO_AI_MODEL", default="")
VIDEO_AI_FALLBACK_MODEL = env("VIDEO_AI_FALLBACK_MODEL", default="")
VIDEO_AI_API_KEY = env("VIDEO_AI_API_KEY", default="")
VIDEO_AI_TIMEOUT = env(
    "VIDEO_AI_TIMEOUT", default=90
)  # batch 40 câu lâu hơn 1 lượt chat  # batch 40 câu lâu hơn 1 lượt chat
AI_FREE_TURNS = env("AI_FREE_TURNS")
AI_PREMIUM_TURNS = env("AI_PREMIUM_TURNS")

# Play Integrity cho điểm game (chống sửa điểm / app repack). Client Android gửi
# `X-Integrity-Token`; máy chủ giải mã qua Play Integrity API bằng service account.
#   off     → bỏ qua header
#   log     → giải mã và ghi verdict vào GameScore.integrity, không chặn (mặc định:
#             iOS chưa có App Attest, build dev/sideload không được Play nhận diện)
#   enforce → từ chối 403 nếu token thiếu hoặc verdict không đạt
PLAY_INTEGRITY_MODE = env("PLAY_INTEGRITY_MODE", default="log")
PLAY_INTEGRITY_PACKAGE_NAME = env("PLAY_INTEGRITY_PACKAGE_NAME", default="amoryzenith.sayfully.app")
PLAY_INTEGRITY_SERVICE_ACCOUNT_FILE = env("PLAY_INTEGRITY_SERVICE_ACCOUNT_FILE", default="")
PLAY_INTEGRITY_MAX_AGE_SEC = env("PLAY_INTEGRITY_MAX_AGE_SEC")

# Người dùng Premium dán link YouTube → tạo video học (apps.content.video_import).
VIDEO_IMPORT_ENABLED = env("VIDEO_IMPORT_ENABLED")
VIDEO_IMPORT_MAX_SEC = env("VIDEO_IMPORT_MAX_SEC")  # từ chối video dài hơn (mặc định 20 phút)
VIDEO_IMPORT_DAILY_LIMIT = env("VIDEO_IMPORT_DAILY_LIMIT")  # số video mỗi người mỗi ngày
VIDEO_IMPORT_SYNC = env("VIDEO_IMPORT_SYNC")  # True: xử lý ngay trong request (dev/test)

# Thanh toán (apps.billing). RevenueCat gửi secret trong header `Authorization`;
# PayOS ký payload bằng checksum key. Trống → webhook trả 401, checkout trả 503.
REVENUECAT_WEBHOOK_SECRET = env("REVENUECAT_WEBHOOK_SECRET")
REVENUECAT_API_KEY = env("REVENUECAT_API_KEY")  # secret v1 key cho POST /billing/sync
PAYOS_WEBHOOK_SECRET = env("PAYOS_WEBHOOK_SECRET")
PAYOS_API_KEY = env("PAYOS_API_KEY")

LANGUAGE_CODE = "vi"
TIME_ZONE = "UTC"  # DB lưu UTC; đổi sang giờ user khi tính streak
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

Q_CLUSTER = {
    "name": "sayfully",
    "workers": 2,
    "timeout": 300,
    "retry": 360,
    "orm": "default",
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
