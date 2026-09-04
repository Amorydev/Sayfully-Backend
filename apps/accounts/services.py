"""Nghiệp vụ tài khoản. API layer chỉ gọi vào đây, không tự xử lý logic."""

import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from apps.common.exceptions import AppError, Conflict, Unauthorized

from .models import SocialAccount, User, UserProfile
from .social import SocialProfile
from .tokens import issue_access, issue_refresh, revoke_all

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ đăng ký
@transaction.atomic
def register_user(email: str, password: str, full_name: str = "") -> User:
    email = User.objects.normalize_email(email)
    try:
        return User.objects.create_user(email=email, password=password, full_name=full_name)
    except IntegrityError as exc:
        raise Conflict("Email đã được đăng ký", code="email_taken") from exc


def authenticate_password(email: str, password: str) -> User:
    """Thông báo lỗi cố ý mơ hồ để không lộ email nào tồn tại."""
    user = User.objects.filter(email__iexact=email).first()
    if user is None or not user.check_password(password):
        raise Unauthorized("Email hoặc mật khẩu không đúng", code="invalid_credentials")
    if user.deleted_at is not None or not user.is_active:
        raise Unauthorized("Tài khoản không hoạt động", code="account_inactive")
    return user


# ------------------------------------------------------------------ social
@transaction.atomic
def login_or_create_social(profile: SocialProfile) -> tuple[User, bool]:
    """Trả (user, vừa tạo mới hay không). Khoá là (provider, uid)."""
    link = (
        SocialAccount.objects.select_related("user")
        .filter(provider=profile.provider, provider_uid=profile.uid)
        .first()
    )
    if link is not None:
        user = link.user
        if user.deleted_at is not None or not user.is_active:
            raise Unauthorized("Tài khoản không hoạt động", code="account_inactive")
        # Apple chỉ gửi email lần đầu — nếu lần này có mà trước chưa lưu thì bổ sung
        if profile.email and not link.email:
            link.email = profile.email
            link.save(update_fields=["email"])
        return user, False

    # Chưa có liên kết: gắn vào tài khoản cùng email nếu có, không thì tạo mới
    user = User.objects.filter(email__iexact=profile.email).first() if profile.email else None
    created = False
    if user is None:
        email = profile.email or f"{profile.provider}_{profile.uid}@users.noreply.sayfully.com"
        user = User.objects.create_user(email=email, password=None, full_name=profile.full_name)
        created = True
    elif user.deleted_at is not None or not user.is_active:
        raise Unauthorized("Tài khoản không hoạt động", code="account_inactive")

    SocialAccount.objects.create(
        user=user, provider=profile.provider, provider_uid=profile.uid, email=profile.email
    )
    return user, created


# ------------------------------------------------------------------ phiên
def start_session(user: User, *, device_name: str = "", ip: str | None = None) -> tuple[str, str]:
    """Cấp cặp token mới cho một lần đăng nhập (family mới)."""
    refresh_raw, _ = issue_refresh(user, device_name=device_name, ip=ip)
    return issue_access(user), refresh_raw


# ------------------------------------------------------------------ mật khẩu
def _send_reset_email(user: User, uid: str, token: str) -> None:
    link = f"{settings.PASSWORD_RESET_URL}?uid={uid}&token={token}"
    subject = "Đặt lại mật khẩu Sayfully"
    body = (
        f"Xin chào {user.full_name or 'bạn'},\n\n"
        f"Nhấn vào liên kết sau để đặt lại mật khẩu (hết hạn sau 30 phút):\n{link}\n\n"
        "Nếu không phải bạn yêu cầu, hãy bỏ qua email này."
    )
    if settings.RESEND_API_KEY:
        import resend

        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send(
            {
                "from": settings.DEFAULT_FROM_EMAIL,
                "to": [user.email],
                "subject": subject,
                "text": body,
            }
        )
    else:
        from django.core.mail import send_mail

        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email])


def request_password_reset(email: str) -> None:
    """Luôn trả về im lặng — không tiết lộ email có tồn tại hay không."""
    user = User.objects.filter(email__iexact=email, deleted_at__isnull=True, is_active=True).first()
    if user is None or not user.has_usable_password():
        log.info("Yêu cầu đặt lại mật khẩu cho email không dùng được")
        return
    uid = urlsafe_base64_encode(force_bytes(str(user.pk)))
    token = default_token_generator.make_token(user)
    _send_reset_email(user, uid, token)


@transaction.atomic
def confirm_password_reset(uid: str, token: str, new_password: str) -> User:
    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        user = User.objects.get(pk=user_id, deleted_at__isnull=True, is_active=True)
    except Exception as exc:
        raise AppError("Liên kết đặt lại không hợp lệ", code="reset_invalid") from exc

    if not default_token_generator.check_token(user, token):
        raise AppError("Liên kết đặt lại đã hết hạn hoặc đã dùng", code="reset_invalid")

    user.set_password(new_password)
    user.save(update_fields=["password"])
    revoke_all(user)  # đổi mật khẩu -> đá mọi thiết bị ra
    return user


@transaction.atomic
def change_password(user: User, old_password: str, new_password: str) -> None:
    if user.has_usable_password() and not user.check_password(old_password):
        raise Unauthorized("Mật khẩu hiện tại không đúng", code="invalid_credentials")
    user.set_password(new_password)
    user.save(update_fields=["password"])
    revoke_all(user)


# ------------------------------------------------------------------ xoá tài khoản
@transaction.atomic
def soft_delete_account(user: User) -> None:
    """Ẩn danh PII ngay, xoá cứng sau 30 ngày bằng job nền.

    Email bị đổi để giải phóng ràng buộc unique, cho phép người dùng đăng ký lại.
    """
    stamp = timezone.now()
    user.email = f"deleted_{user.pk}@deleted.sayfully.com"
    user.full_name = ""
    user.avatar_path = ""
    user.is_active = False
    user.deleted_at = stamp
    user.set_unusable_password()
    user.save(
        update_fields=["email", "full_name", "avatar_path", "is_active", "deleted_at", "password"]
    )
    user.social_accounts.all().delete()
    revoke_all(user)


def ensure_profile(user: User) -> UserProfile:
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile
