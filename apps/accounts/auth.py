"""Xác thực 2 chế độ.

    Mobile (Flutter) : Authorization: Bearer <access>, refresh trong body
    Web (Next.js)    : Authorization: Bearer <access>, refresh trong httpOnly cookie

Client khai báo mình là ai qua header `X-Client-Type: web | mobile` (mặc định mobile).
"""

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from ninja.security import HttpBearer

from apps.common.exceptions import Unauthorized

from .models import User
from .tokens import decode_access

CLIENT_HEADER = "X-Client-Type"
WEB = "web"
MOBILE = "mobile"


def client_type(request: HttpRequest) -> str:
    value = request.headers.get(CLIENT_HEADER, MOBILE).strip().lower()
    return WEB if value == WEB else MOBILE


def is_web(request: HttpRequest) -> bool:
    return client_type(request) == WEB


class BearerAuth(HttpBearer):
    """Dùng cho mọi endpoint cần đăng nhập, cả mobile lẫn web."""

    def authenticate(self, request: HttpRequest, token: str) -> User:
        user_id = decode_access(token)
        user = User.objects.filter(id=user_id, deleted_at__isnull=True, is_active=True).first()
        if user is None:
            raise Unauthorized(
                "Tài khoản không tồn tại hoặc đã bị vô hiệu hoá", code="account_inactive"
            )
        request.user = user
        return user


bearer_auth = BearerAuth()


# ------------------------------------------------------------------ cookie
def read_refresh(request: HttpRequest, body_token: str | None) -> str:
    """Lấy refresh token: web đọc từ cookie, mobile đọc từ body."""
    if is_web(request):
        raw = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if not raw:
            raise Unauthorized("Thiếu refresh cookie", code="refresh_missing")
        return raw
    if not body_token:
        raise Unauthorized("Thiếu refresh token", code="refresh_missing")
    return body_token


def set_refresh_cookie(response: HttpResponse, raw: str) -> None:
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        raw,
        max_age=settings.REFRESH_TOKEN_DAYS * 24 * 3600,
        httponly=True,  # JS không đọc được -> chống XSS
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        path=settings.REFRESH_COOKIE_PATH,
        domain=settings.REFRESH_COOKIE_DOMAIN,
    )


def clear_refresh_cookie(response: HttpResponse) -> None:
    response.delete_cookie(
        settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        domain=settings.REFRESH_COOKIE_DOMAIN,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


def device_of(request: HttpRequest) -> str:
    return request.headers.get("User-Agent", "")[:120]


def ip_of(request: HttpRequest) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
