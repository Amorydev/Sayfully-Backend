"""Quảng cáo — cấu hình vị trí (bật/tắt, trần, thưởng) + sổ cái lượt hiển thị.

Hai nguyên tắc chi phối toàn bộ app này:

1. **Client không tự cộng thưởng.** Một lượt quảng cáo có thưởng đi ba bước:
   xin vé (:class:`AdImpression` ``PENDING``) → mạng quảng cáo gọi SSV → server cộng thưởng.
2. **Trần và khoảng cách do server quyết định.** Client chỉ hiển thị phần còn lại
   (``3/3 hôm nay``); mọi phép đếm thật nằm ở sổ cái này, tính theo ngày của hồ sơ.
"""

import uuid

from django.db import models

from apps.accounts.models import User


class AdPlacement(models.Model):
    """Một vị trí quảng cáo trong app. Sửa ở admin = đổi hành vi không cần phát hành bản mới."""

    class Format(models.TextChoices):
        REWARDED = "rewarded", "Có thưởng"
        REWARDED_INTERSTITIAL = "rewarded_interstitial", "Xen kẽ có thưởng"
        INTERSTITIAL = "interstitial", "Xen kẽ"
        NATIVE = "native", "Native"

    class Reward(models.TextChoices):
        NONE = "none", "Không thưởng"
        COINS = "coins", "Xu"
        HEARTS = "hearts", "Tim"

    class RewardSource(models.TextChoices):
        FIXED = "fixed", "Cố định"
        LAST_GAME_COINS = "last_game_coins", "Bằng xu ván vừa chơi"
        LAST_COIN_REWARD = "last_coin_reward", "Bằng xu vừa nhận (theo lý do)"

    slot = models.SlugField(max_length=48, unique=True)
    title_vi = models.CharField(max_length=120)
    description_vi = models.CharField(max_length=255, blank=True)
    format = models.CharField(max_length=24, choices=Format.choices, default=Format.REWARDED)
    reward_kind = models.CharField(max_length=16, choices=Reward.choices, default=Reward.NONE)
    # Với `last_game_coins`, `reward_amount` là **trần**: thưởng thật bằng số xu ván vừa chơi,
    # nên "nhân đôi xu" đúng nghĩa thay vì luôn trả kịch trần.
    reward_source = models.CharField(
        max_length=24, choices=RewardSource.choices, default=RewardSource.FIXED
    )
    # Với `last_coin_reward`: lý do trong sổ cái xu để soi (vd. "checkin", "challenge").
    reward_reason = models.CharField(max_length=48, blank=True)
    reward_amount = models.PositiveSmallIntegerField(default=0)
    is_enabled = models.BooleanField(default=False)
    daily_cap = models.PositiveSmallIntegerField(default=3)
    cooldown_seconds = models.PositiveIntegerField(default=60)
    ad_unit_android = models.CharField(max_length=128, blank=True)
    ad_unit_ios = models.CharField(max_length=128, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "slot"]

    def __str__(self) -> str:
        return f"{self.slot} ({self.format})"


class AdImpression(models.Model):
    """Một lượt quảng cáo đã mở. Là đơn vị đếm trần ngày *và* chứng từ để cộng thưởng.

    Vé được tạo lúc client xin mở quảng cáo nên **lượt bỏ giữa chừng vẫn tính trần** —
    nếu không, đóng quảng cáo rồi mở lại là cách farm thưởng dễ nhất.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Chờ xác thực"
        REWARDED = "rewarded", "Đã thưởng"
        REJECTED = "rejected", "Từ chối"
        EXPIRED = "expired", "Hết hạn"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ad_impressions")
    placement = models.ForeignKey(AdPlacement, on_delete=models.PROTECT, related_name="impressions")
    slot = models.SlugField(max_length=48)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    reward_kind = models.CharField(max_length=16, default=AdPlacement.Reward.NONE)
    # Với `last_coin_reward`: lý do trong sổ cái xu để soi (vd. "checkin", "challenge").
    reward_reason = models.CharField(max_length=48, blank=True)
    reward_amount = models.PositiveSmallIntegerField(default=0)
    granted_amount = models.PositiveSmallIntegerField(default=0)
    # Ngày theo timezone hồ sơ — đơn vị tính trần, không dùng ngày UTC của created_at.
    local_date = models.DateField()
    # Nguồn đã dùng để tính thưởng (vd. "game_score:12") — một ván chỉ được nhân đôi một lần.
    reward_ref = models.CharField(max_length=64, blank=True)
    ad_network = models.CharField(max_length=32, blank=True)
    ad_unit = models.CharField(max_length=128, blank=True)
    ssv_transaction_id = models.CharField(max_length=128, blank=True)
    signature_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    rewarded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "local_date"], name="ad_user_day_idx"),
            models.Index(fields=["user", "-created_at"], name="ad_user_recent_idx"),
            models.Index(fields=["user", "reward_ref"], name="ad_user_ref_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["ssv_transaction_id"],
                condition=~models.Q(ssv_transaction_id=""),
                name="ad_ssv_transaction_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.slot} {self.status}"
