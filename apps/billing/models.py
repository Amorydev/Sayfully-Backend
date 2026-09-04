from django.db import models

from apps.accounts.models import User


class Product(models.Model):
    class Period(models.TextChoices):
        MONTH = "month", "Tháng"
        YEAR = "year", "Năm"
        LIFETIME = "lifetime", "Trọn đời"

    code = models.SlugField(max_length=48, unique=True)  # premium_year | premium_lifetime
    name_vi = models.CharField(max_length=64)
    period = models.CharField(max_length=10, choices=Period.choices)
    price = models.PositiveIntegerField()
    original_price = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="VND")
    trial_days = models.PositiveSmallIntegerField(default=0)
    badge_vi = models.CharField(max_length=32, blank=True)  # "TIẾT KIỆM 50%"
    features = models.JSONField(default=list)
    store_ids = models.JSONField(default=dict)  # {"revenuecat": "...", "payos": "..."}
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return str(self.code)


class Subscription(models.Model):
    class Provider(models.TextChoices):
        REVENUECAT = "revenuecat", "RevenueCat"
        PAYOS = "payos", "PayOS"
        GIFT = "gift", "Mã quà tặng"

    class Status(models.TextChoices):
        ACTIVE = "active", "Đang hiệu lực"
        EXPIRED = "expired", "Hết hạn"
        CANCELLED = "cancelled", "Đã huỷ"
        GRACE = "grace", "Gia hạn lỗi"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="subscriptions")
    provider = models.CharField(max_length=16, choices=Provider.choices)
    product_code = models.CharField(max_length=64)  # premium_year | premium_lifetime
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    store = models.CharField(max_length=16, blank=True)  # play_store | app_store | web
    started_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)  # null = trọn đời
    original_txn_id = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-started_at"], name="sub_user_recent_idx"),
            models.Index(
                fields=["expires_at"], name="sub_expiry_idx", condition=models.Q(status="active")
            ),  # job hạ cấp mỗi ngày
        ]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.product_code} · {self.status}"


class PaymentEvent(models.Model):
    """Log webhook thô — event_id unique để đảm bảo idempotency."""

    provider = models.CharField(max_length=16)
    event_id = models.CharField(max_length=128, unique=True)
    event_type = models.CharField(max_length=64)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    payload = models.JSONField()
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["provider", "-created_at"], name="pe_provider_idx")]

    def __str__(self) -> str:
        return f"{self.provider}:{self.event_id}"


class GiftCode(models.Model):
    code = models.CharField(max_length=32, unique=True)
    days = models.PositiveSmallIntegerField()
    max_uses = models.PositiveIntegerField(default=1)
    used_count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return str(self.code)


class GiftCodeRedemption(models.Model):
    gift_code = models.ForeignKey(GiftCode, on_delete=models.CASCADE, related_name="redemptions")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    redeemed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["gift_code", "user"], name="uniq_redeem")]

    def __str__(self) -> str:
        return f"{self.gift_code_id} · {self.user_id}"
