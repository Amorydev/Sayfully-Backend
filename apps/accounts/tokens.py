"""Tầng token: access (JWT, stateless) + refresh (opaque, lưu hash trong DB).

Refresh cố ý KHÔNG dùng JWT để có thể thu hồi: đăng xuất, đổi mật khẩu,
xoá tài khoản, và thu hồi cả family khi phát hiện token bị đánh cắp.
"""

import hashlib
import secrets
import uuid
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone

from apps.common.exceptions import Unauthorized

from .models import RefreshToken, User

ACCESS_TYPE = "access"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ access
def issue_access(user: User) -> str:
    now = timezone.now()
    payload = {
        "sub": str(user.id),
        "typ": ACCESS_TYPE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.JWT_SIGNING_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access(token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.JWT_SIGNING_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Access token đã hết hạn", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthorized("Access token không hợp lệ", code="token_invalid") from exc

    if payload.get("typ") != ACCESS_TYPE:
        raise Unauthorized("Sai loại token", code="token_wrong_type")
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise Unauthorized("Token thiếu chủ thể hợp lệ", code="token_invalid") from exc


# ------------------------------------------------------------------ refresh
def issue_refresh(
    user: User,
    *,
    family_id: uuid.UUID | None = None,
    device_name: str = "",
    ip: str | None = None,
) -> tuple[str, RefreshToken]:
    """Trả (chuỗi gốc, bản ghi). Chuỗi gốc CHỈ trả về client, DB chỉ giữ hash."""
    raw = secrets.token_urlsafe(32)  # 256 bit
    obj = RefreshToken.objects.create(
        user=user,
        token_hash=_hash(raw),
        family_id=family_id or uuid.uuid4(),
        device_name=device_name[:120],
        ip=ip,
        expires_at=timezone.now() + timedelta(days=settings.REFRESH_TOKEN_DAYS),
    )
    return raw, obj


def rotate_refresh(
    raw: str, *, device_name: str = "", ip: str | None = None
) -> tuple[User, str, str]:
    """Xoay refresh token. Trả (user, access mới, refresh mới).

    Phát hiện tái sử dụng: nếu token đã bị thu hồi mà vẫn được dùng, coi như
    bị đánh cắp -> thu hồi TOÀN BỘ family, buộc đăng nhập lại.

    CỐ Ý KHÔNG bọc cả hàm trong transaction.atomic: việc thu hồi family phải
    được commit TRƯỚC khi ném lỗi, nếu không rollback sẽ xoá mất nó.
    """
    token_hash = _hash(raw)
    existing = RefreshToken.objects.select_related("user").filter(token_hash=token_hash).first()

    if existing is None:
        raise Unauthorized("Refresh token không hợp lệ", code="refresh_invalid")

    if existing.revoked_at is not None:
        revoke_family(existing.family_id)
        raise Unauthorized(
            "Refresh token đã bị thu hồi — nghi ngờ bị đánh cắp, vui lòng đăng nhập lại",
            code="refresh_reused",
        )

    if existing.expires_at <= timezone.now():
        raise Unauthorized("Refresh token đã hết hạn", code="refresh_expired")

    user = existing.user
    if user.deleted_at is not None or not user.is_active:
        raise Unauthorized("Tài khoản không hoạt động", code="account_inactive")

    # UPDATE có điều kiện là thao tác nguyên tử của Postgres: nếu hai request
    # cùng xoay một token, chỉ đúng một request thắng.
    won = RefreshToken.objects.filter(pk=existing.pk, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )

    if not won:
        revoke_family(existing.family_id)
        raise Unauthorized(
            "Refresh token đã bị thu hồi — nghi ngờ bị đánh cắp, vui lòng đăng nhập lại",
            code="refresh_reused",
        )

    new_raw, _ = issue_refresh(
        user,
        family_id=existing.family_id,
        device_name=device_name or existing.device_name,
        ip=ip,
    )
    return user, issue_access(user), new_raw


def revoke(raw: str) -> bool:
    """Thu hồi đúng một token. Trả True nếu có gì đó bị thu hồi."""
    updated = RefreshToken.objects.filter(token_hash=_hash(raw), revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    return bool(updated)


def revoke_family(family_id: uuid.UUID) -> int:
    return RefreshToken.objects.filter(family_id=family_id, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


def revoke_all(user: User) -> int:
    """Dùng khi đổi mật khẩu, đăng xuất mọi thiết bị, xoá tài khoản."""
    return RefreshToken.objects.filter(user=user, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
