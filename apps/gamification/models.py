from django.db import models

from apps.accounts.models import User
from apps.common.models import CEFR


class Challenge(models.Model):
    class Scope(models.TextChoices):
        DAILY = "daily", "Hằng ngày"
        WEEKLY = "weekly", "Hằng tuần"
        MILESTONE = "milestone", "Cột mốc"

    class Metric(models.TextChoices):
        XP = "xp", "XP"
        WORDS = "words", "Từ đã ôn"
        LESSONS = "lessons", "Bài học"
        DAYS = "days", "Ngày học"
        SPEAKING = "speaking", "Câu đã nói"
        EXAMS = "exams", "Đề thi"

    code = models.SlugField(max_length=48, unique=True)
    scope = models.CharField(max_length=10, choices=Scope.choices)
    metric = models.CharField(max_length=10, choices=Metric.choices)
    title_vi = models.CharField(max_length=128)
    description_vi = models.CharField(max_length=255, blank=True)
    target = models.PositiveIntegerField()
    tier = models.PositiveSmallIntegerField(default=1)  # cột mốc nhiều cấp
    reward_xp = models.PositiveSmallIntegerField(default=0)
    reward_coins = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return str(self.code)


class UserChallenge(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="challenges")
    challenge = models.ForeignKey(Challenge, on_delete=models.CASCADE, related_name="user_states")
    period_key = models.CharField(max_length=16)  # "2026-09-03" | "2026-W36" | "lifetime"
    progress = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "challenge", "period_key"], name="uniq_user_challenge"
            ),
        ]
        indexes = [models.Index(fields=["user", "period_key"], name="uc_user_period_idx")]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.challenge_id} · {self.period_key}"


class Badge(models.Model):
    code = models.SlugField(max_length=48, unique=True)
    title_vi = models.CharField(max_length=128)
    description_vi = models.CharField(max_length=255)
    icon_path = models.CharField(max_length=255, blank=True)
    condition = models.JSONField(default=dict)  # {"metric":"streak","value":7}
    order = models.PositiveSmallIntegerField(default=0)

    def __str__(self) -> str:
        return str(self.code)


class UserBadge(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="badges")
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE)
    unlocked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "badge"], name="uniq_user_badge")]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.badge_id}"


class LeagueGroup(models.Model):
    """Mỗi tuần chia user thành nhóm ~30 người cùng bậc."""

    class Tier(models.IntegerChoices):
        BRONZE = 1, "Đồng"
        SILVER = 2, "Bạc"
        GOLD = 3, "Vàng"
        PLATINUM = 4, "Bạch kim"
        DIAMOND = 5, "Kim cương"

    tier = models.SmallIntegerField(choices=Tier.choices)
    iso_year = models.PositiveSmallIntegerField()
    iso_week = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["iso_year", "iso_week", "tier"], name="league_period_idx")]

    def __str__(self) -> str:
        return f"{self.get_tier_display()} {self.iso_year}-W{self.iso_week:02d}"


class LeagueMembership(models.Model):
    group = models.ForeignKey(LeagueGroup, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="league_memberships")
    xp_week = models.PositiveIntegerField(default=0)
    rank = models.PositiveSmallIntegerField(null=True, blank=True)  # chốt cuối tuần
    promoted = models.BooleanField(null=True)  # True thăng / False rớt

    class Meta:
        constraints = [models.UniqueConstraint(fields=["group", "user"], name="uniq_league_member")]
        indexes = [
            # ⭐ Xếp hạng trong liên đoàn
            models.Index(fields=["group", "-xp_week"], name="league_rank_idx"),
            models.Index(fields=["user"], name="league_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} trong nhóm {self.group_id}"


class ShopItem(models.Model):
    code = models.SlugField(max_length=48, unique=True)  # refill_hearts | streak_freeze | gift_box
    title_vi = models.CharField(max_length=128)
    description_vi = models.CharField(max_length=255)
    cost_coins = models.PositiveIntegerField()
    effect = models.JSONField(default=dict)  # {"hearts":5} | {"streak_freeze":1}
    icon_path = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return str(self.code)


class CoinTransaction(models.Model):
    """Sổ cái xu — bắt buộc có để đối soát và chống gian lận."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="coin_transactions")
    amount = models.IntegerField()  # + nhận, - tiêu
    reason = models.CharField(max_length=48)  # checkin | challenge | game | shop_purchase
    ref_type = models.CharField(max_length=32, blank=True)
    ref_id = models.CharField(max_length=64, blank=True)
    balance_after = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "-created_at"], name="coin_user_recent_idx")]

    def __str__(self) -> str:
        return f"{self.user_id} {self.amount:+d} {self.reason}"


class Game(models.Model):
    """Mini-game trong sảnh Trò chơi (C12, C31)."""

    class Kind(models.TextChoices):
        REFLEX = "reflex", "Phản xạ"
        MEMORY = "memory", "Ghi nhớ"
        LISTENING = "listening", "Nghe hiểu"

    code = models.SlugField(max_length=32, unique=True)  # word_rain | stress_master | match_pairs
    title_vi = models.CharField(max_length=64)
    description_vi = models.CharField(max_length=255)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    icon_path = models.CharField(max_length=255, blank=True)
    min_level = models.CharField(max_length=2, choices=CEFR.choices, default=CEFR.A1)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return self.title_vi


class GameScore(models.Model):
    """Một ván chơi. Kỷ lục cá nhân = MAX(score) theo (user, game)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="game_scores")
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="scores")
    level = models.CharField(max_length=2, choices=CEFR.choices)
    score = models.PositiveIntegerField()
    accuracy = models.FloatField(default=0)  # 0..1
    coins_earned = models.PositiveSmallIntegerField(default=0)
    played_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "game", "-score"], name="gs_user_best_idx"),
            models.Index(fields=["game", "-score"], name="gs_game_rank_idx"),
            models.Index(fields=["user", "-played_at"], name="gs_user_recent_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.game_id} · {self.score}"
