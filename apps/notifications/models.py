"""Thông báo trong app (C46) và thiết bị nhận push (FCM) để nhắc streak."""

from django.db import models

from apps.accounts.models import User


class Device(models.Model):
    class Platform(models.TextChoices):
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"
        WEB = "web", "Web"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    fcm_token = models.CharField(max_length=512, unique=True)
    platform = models.CharField(max_length=8, choices=Platform.choices)
    app_version = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "devices"
        indexes = [models.Index(fields=["user", "is_active"], name="device_user_active_idx")]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.platform}"


class Notification(models.Model):
    class Kind(models.TextChoices):
        STREAK = "streak", "Nhắc streak"
        REWARD = "reward", "Phần thưởng"
        EVENT = "event", "Sự kiện"
        SYSTEM = "system", "Hệ thống"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    title_vi = models.CharField(max_length=160)
    body_vi = models.CharField(max_length=512, blank=True)
    data = models.JSONField(default=dict, blank=True)  # deep-link: {"screen": "C13"}
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        indexes = [
            models.Index(fields=["user", "-created_at"], name="notif_user_recent_idx"),
            # Đếm chưa đọc cho chấm đỏ trên chuông — partial index rất nhỏ
            models.Index(
                fields=["user"], name="notif_unread_idx", condition=models.Q(read_at__isnull=True)
            ),
        ]

    def __str__(self) -> str:
        return str(self.title_vi)
