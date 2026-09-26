"""Nghiệp vụ tài khoản. API layer chỉ gọi vào đây, không tự xử lý logic."""

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from apps.common.exceptions import AppError, Conflict, RateLimited, Unauthorized

from .models import EmailVerification, SocialAccount, User, UserProfile
from .social import SocialProfile
from .tokens import issue_access, issue_refresh, revoke_all

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ đăng ký
@transaction.atomic
def register_user(email: str, password: str, full_name: str = "") -> User:
    """Tạo tài khoản chưa xác minh email.

    Email đang thuộc một tài khoản chưa từng xác minh thì được đăng ký lại: người gõ nhầm email
    không giữ chỗ mãi của chủ thật, và tài khoản đó chưa qua được bước xác minh nên chưa có gì để mất.
    """
    email = User.objects.normalize_email(email)
    stale = (
        User.objects.active()
        .filter(email__iexact=email, email_verified=False, social_accounts__isnull=True)
        .first()
    )
    if stale is not None:
        stale.set_password(password)
        stale.full_name = full_name
        stale.save(update_fields=["password", "full_name"])
        revoke_all(stale)
        return stale
    try:
        return User.objects.create_user(
            email=email, password=password, full_name=full_name, email_verified=False
        )
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
    elif not user.email_verified and profile.email_verified:
        # Google/Apple đã xác nhận chủ email nên không cần mã nữa.
        user.email_verified = True
        user.save(update_fields=["email_verified"])

    SocialAccount.objects.create(
        user=user, provider=profile.provider, provider_uid=profile.uid, email=profile.email
    )
    return user, created


# ------------------------------------------------------------------ phiên
def start_session(user: User, *, device_name: str = "", ip: str | None = None) -> tuple[str, str]:
    """Cấp cặp token mới cho một lần đăng nhập (family mới)."""
    refresh_raw, _ = issue_refresh(user, device_name=device_name, ip=ip)
    return issue_access(user), refresh_raw


# ------------------------------------------------------------------ email
def _send_email(to: str, subject: str, body: str) -> None:
    if settings.RESEND_API_KEY:
        import resend

        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send(
            {
                "from": settings.DEFAULT_FROM_EMAIL,
                "to": [to],
                "subject": subject,
                "text": body,
            }
        )
    else:
        from django.core.mail import send_mail

        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to])


# ------------------------------------------------------------------ xác minh email
VERIFY_CODE_TTL = timedelta(minutes=10)
VERIFY_RESEND_COOLDOWN = timedelta(seconds=60)
VERIFY_MAX_ATTEMPTS = 5


def _code_hash(user: User, code: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(), f"{user.pk}:{code}".encode(), hashlib.sha256
    ).hexdigest()


def send_verification_code(user: User, *, enforce_cooldown: bool = True) -> None:
    """Tạo mã 6 số mới (mã cũ mất hiệu lực) rồi gửi email. Gửi lại quá dày thì báo 429."""
    if user.email_verified:
        return
    now = timezone.now()
    current = EmailVerification.objects.filter(user=user).first()
    if enforce_cooldown and current is not None and now - current.sent_at < VERIFY_RESEND_COOLDOWN:
        wait = int((VERIFY_RESEND_COOLDOWN - (now - current.sent_at)).total_seconds()) + 1
        raise RateLimited(
            f"Vui lòng đợi {wait} giây để gửi lại mã",
            code="verify_resend_too_soon",
            details={"retry_after": [str(wait)]},
        )
    code = f"{secrets.randbelow(1_000_000):06d}"
    EmailVerification.objects.update_or_create(
        user=user,
        defaults={
            "code_hash": _code_hash(user, code),
            "sent_at": now,
            "expires_at": now + VERIFY_CODE_TTL,
            "attempts": 0,
        },
    )
    _send_email(
        user.email,
        f"{code} là mã xác minh Sayfully của bạn",
        f"Xin chào {user.full_name or 'bạn'},\n\n"
        f"Mã xác minh email của bạn là: {code}\n\n"
        "Mã có hiệu lực trong 10 phút. Nếu không phải bạn đăng ký Sayfully, hãy bỏ qua email này.",
    )


def verify_email_code(user: User, code: str) -> None:
    """Không bọc transaction: lần nhập sai phải được lưu lại dù hàm kết thúc bằng lỗi."""
    if user.email_verified:
        return
    record = EmailVerification.objects.filter(user=user).first()
    if record is None or record.expires_at <= timezone.now():
        raise AppError("Mã đã hết hạn, hãy gửi lại mã mới", code="verify_code_expired")
    if record.attempts >= VERIFY_MAX_ATTEMPTS:
        raise AppError("Nhập sai quá nhiều lần, hãy gửi lại mã mới", code="verify_code_locked")
    if not hmac.compare_digest(record.code_hash, _code_hash(user, code.strip())):
        record.attempts += 1
        record.save(update_fields=["attempts"])
        left = VERIFY_MAX_ATTEMPTS - record.attempts
        if left == 0:
            raise AppError("Nhập sai quá nhiều lần, hãy gửi lại mã mới", code="verify_code_locked")
        raise AppError(
            f"Mã chưa đúng, bạn còn {left} lần thử",
            code="verify_code_invalid",
            details={"attempts_left": [str(left)]},
        )
    user.email_verified = True
    user.save(update_fields=["email_verified"])
    record.delete()


# ------------------------------------------------------------------ mật khẩu
def _send_reset_email(user: User, uid: str, token: str) -> None:
    link = f"{settings.PASSWORD_RESET_URL}?uid={uid}&token={token}"
    _send_email(
        user.email,
        "Đặt lại mật khẩu Sayfully",
        f"Xin chào {user.full_name or 'bạn'},\n\n"
        f"Nhấn vào liên kết sau để đặt lại mật khẩu (hết hạn sau 30 phút):\n{link}\n\n"
        "Nếu không phải bạn yêu cầu, hãy bỏ qua email này.",
    )


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
    if profile.is_premium:
        from apps.billing.services import expire_lapsed  # noqa: PLC0415 — tránh import vòng

        expire_lapsed(profile)
    return profile
