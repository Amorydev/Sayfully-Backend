"""Định danh người dùng + trạng thái học.

Nguyên tắc:
- `User` giữ thông tin định danh, hiếm khi đổi.
- `UserProfile` giữ XP/xu/tim/streak — ghi rất thường xuyên, tách ra để không
  khoá bảng auth.
- `RefreshToken` lưu HASH, không lưu token gốc.
"""

import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.common.models import CEFR, Accent, TimeStampedModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email: str, password: str | None = None, **extra):
        if not email:
            raise ValueError("Email là bắt buộc")
        user = self.model(email=self.normalize_email(email), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()  # tài khoản đăng nhập bằng Google/Apple
        user.save(using=self._db)
        UserProfile.objects.create(user=user)
        return user

    def create_superuser(self, email: str, password: str, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if not extra.get("is_staff") or not extra.get("is_superuser"):
            raise ValueError("Superuser phải có is_staff và is_superuser = True")
        return self.create_user(email, password, **extra)

    def active(self):
        """Tài khoản còn dùng được. Dùng TƯỜNG MINH ở luồng auth.

        Cố ý KHÔNG lọc trong get_queryset(): lọc ngầm dễ che giấu lỗi và gây
        khó hiểu ở admin/FK.
        """
        return self.get_queryset().filter(deleted_at__isnull=True, is_active=True)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=120, blank=True)
    avatar_path = models.CharField(max_length=255, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    deleted_at = models.DateTimeField(null=True, blank=True)  # xoá mềm, purge sau 30 ngày

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        db_table = "users"
        indexes = [
            models.Index(
                fields=["deleted_at"],
                name="user_deleted_idx",
                condition=models.Q(deleted_at__isnull=False),
            ),
        ]

    def __str__(self) -> str:
        return self.email

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class SocialAccount(TimeStampedModel):
    """Liên kết tài khoản mạng xã hội.

    Khoá định danh là (provider, provider_uid) — KHÔNG dùng email vì email có thể
    đổi hoặc là relay của Apple (@privaterelay.appleid.com).
    """

    class Provider(models.TextChoices):
        GOOGLE = "google", "Google"
        APPLE = "apple", "Apple"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="social_accounts")
    provider = models.CharField(max_length=16, choices=Provider.choices)
    provider_uid = models.CharField(max_length=255)
    email = models.EmailField(blank=True)

    class Meta:
        db_table = "social_accounts"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_uid"], name="uniq_social_provider_uid"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.provider_uid}"


class RefreshToken(models.Model):
    """Refresh token dạng opaque.

    Chỉ lưu SHA-256 hash. Mỗi lần đăng nhập tạo một `family_id`; khi xoay vòng,
    token cũ bị thu hồi và token mới giữ nguyên family. Nếu một token ĐÃ thu hồi
    được dùng lại -> dấu hiệu bị đánh cắp -> thu hồi cả family.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="refresh_tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    family_id = models.UUIDField(default=uuid.uuid4)
    device_name = models.CharField(max_length=120, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "refresh_tokens"
        indexes = [
            models.Index(fields=["user", "revoked_at"], name="rt_user_active_idx"),
            models.Index(fields=["family_id"], name="rt_family_idx"),
            models.Index(fields=["expires_at"], name="rt_expiry_idx"),
        ]

    def __str__(self) -> str:
        return f"RT({self.user_id}, {'revoked' if self.revoked_at else 'active'})"

    @property
    def is_valid(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()


class UserProfile(models.Model):
    """Trạng thái học. Mọi thay đổi XP/xu/tim phải đi qua service phía server."""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, primary_key=True, related_name="profile"
    )

    cefr_level = models.CharField(max_length=2, choices=CEFR.choices, default=CEFR.A1)
    goal_level = models.CharField(max_length=2, choices=CEFR.choices, default=CEFR.B1)

    xp_total = models.PositiveIntegerField(default=0)
    level = models.PositiveSmallIntegerField(default=1)
    coins = models.PositiveIntegerField(default=0)

    hearts = models.PositiveSmallIntegerField(default=5)
    hearts_updated_at = models.DateTimeField(default=timezone.now)

    streak_current = models.PositiveIntegerField(default=0)
    streak_best = models.PositiveIntegerField(default=0)
    streak_freezes = models.PositiveSmallIntegerField(default=0)
    last_active_date = models.DateField(null=True, blank=True)

    accent = models.CharField(max_length=2, choices=Accent.choices, default=Accent.US)
    show_ipa = models.BooleanField(default=True)
    daily_goal_xp = models.PositiveSmallIntegerField(default=50)
    timezone = models.CharField(max_length=40, default="Asia/Ho_Chi_Minh")

    is_premium = models.BooleanField(default=False)
    premium_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "user_profiles"
        indexes = [
            models.Index(fields=["last_active_date"], name="profile_lastactive_idx"),
        ]

    def __str__(self) -> str:
        return f"Profile({self.user_id})"
