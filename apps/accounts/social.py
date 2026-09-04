"""Xác thực token đăng nhập mạng xã hội.

Hai bẫy thường gặp đã xử lý ở đây:
1. Google có 3 client ID KHÁC NHAU (Android / iOS / Web) — phải chấp nhận cả ba.
2. Apple CHỈ trả email + tên ở lần đăng nhập đầu tiên — gọi nơi khác phải lưu ngay.
"""

from dataclasses import dataclass

import jwt
from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from jwt import PyJWKClient

from apps.common.exceptions import AppError, Unauthorized

APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


@dataclass(frozen=True)
class SocialProfile:
    provider: str
    uid: str  # 'sub' — định danh ổn định, KHÔNG dùng email
    email: str = ""
    full_name: str = ""
    email_verified: bool = False


_apple_jwks = PyJWKClient(APPLE_KEYS_URL, cache_keys=True, lifespan=86_400)


def verify_google_id_token(token: str) -> SocialProfile:
    if not settings.GOOGLE_CLIENT_IDS:
        raise AppError("Chưa cấu hình GOOGLE_CLIENT_ID_*", code="config_missing", status_code=500)

    try:
        # audience=None -> tự kiểm 'aud' bên dưới vì có nhiều client ID hợp lệ
        info = google_id_token.verify_oauth2_token(token, google_requests.Request(), audience=None)
    except ValueError as exc:
        raise Unauthorized("Google token không hợp lệ", code="google_invalid") from exc

    if info.get("iss") not in GOOGLE_ISSUERS:
        raise Unauthorized("Google token sai issuer", code="google_bad_issuer")

    if info.get("aud") not in settings.GOOGLE_CLIENT_IDS:
        raise Unauthorized("Google token không dành cho ứng dụng này", code="google_bad_audience")

    sub = info.get("sub")
    if not sub:
        raise Unauthorized("Google token thiếu 'sub'", code="google_invalid")

    return SocialProfile(
        provider="google",
        uid=sub,
        email=info.get("email", "") or "",
        full_name=info.get("name", "") or "",
        email_verified=bool(info.get("email_verified")),
    )


def verify_apple_identity_token(token: str) -> SocialProfile:
    if not settings.APPLE_AUDIENCES:
        raise AppError(
            "Chưa cấu hình APPLE_BUNDLE_ID / APPLE_SERVICE_ID",
            code="config_missing",
            status_code=500,
        )

    try:
        signing_key = _apple_jwks.get_signing_key_from_jwt(token)
        info = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.APPLE_AUDIENCES,  # PyJWT chấp nhận danh sách
            issuer=APPLE_ISSUER,
        )
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Apple token đã hết hạn", code="apple_expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise Unauthorized(
            "Apple token không dành cho ứng dụng này", code="apple_bad_audience"
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthorized("Apple token không hợp lệ", code="apple_invalid") from exc
    except Exception as exc:  # lỗi mạng khi lấy JWKS
        raise AppError(
            "Không lấy được khoá công khai của Apple",
            code="apple_jwks_unavailable",
            status_code=503,
        ) from exc

    sub = info.get("sub")
    if not sub:
        raise Unauthorized("Apple token thiếu 'sub'", code="apple_invalid")

    return SocialProfile(
        provider="apple",
        uid=sub,
        email=info.get("email", "") or "",
        email_verified=bool(info.get("email_verified") in (True, "true")),
    )
