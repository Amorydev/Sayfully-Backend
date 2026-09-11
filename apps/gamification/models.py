import math

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


class GameStageProgress(models.Model):
    """
    Tiến độ path map của mini-game: mỗi cấp CEFR chia thành các chặng liên tiếp
    (mặc định 25 từ/chặng), cắt từ danh sách từ vựng của cấp theo thứ tự cố định
    ``(frequency_rank, headword)`` — trùng thứ tự của ``GET /content/vocabulary``,
    nên ``stage_index`` luôn ánh xạ về đúng ``offset = stage_index * stage_size``.

    Một dòng = một chặng người dùng đã hoàn thành. Chặng kế tiếp mở khoá khi
    chặng liền trước có dòng ở đây.
    """

    STAGE_SIZE = 25

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="game_stages")
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="stages")
    level = models.CharField(max_length=2, choices=CEFR.choices)
    stage_index = models.PositiveSmallIntegerField()  # 0-based
    best_score = models.PositiveIntegerField(default=0)
    best_accuracy = models.FloatField(default=0)  # 0..1
    play_count = models.PositiveSmallIntegerField(default=0)
    completed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "game", "level", "stage_index"],
                name="uniq_user_game_level_stage",
            )
        ]
        indexes = [
            models.Index(fields=["user", "game", "level"], name="gsp_user_level_idx"),
        ]
        ordering = ["level", "stage_index"]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.game_id} · {self.level}#{self.stage_index}"


class MatchPairsStageQuerySet(models.QuerySet):
    def with_pair_count(self):
        # distinct=True: ChangeList.distinct() chạy sau GROUP BY nên không bảo vệ
        # aggregate; lọc qua `progress__` trong admin sẽ nhân đôi nếu thiếu nó.
        return self.annotate(pair_count=models.Count("pairs", distinct=True))

    def playable(self):
        """
        Nơi duy nhất định nghĩa "chơi được": đang bật và đủ cặp cho Siêu cấp.

        Sắp xếp ngay tại đây (`order`, `id`) vì Django bỏ `Meta.ordering` trên
        truy vấn có GROUP BY (do `with_pair_count()` gây ra) — không tự sắp thì
        thứ tự tuỳ ý, làm hỏng chuỗi mở khoá.
        """
        return (
            self.filter(is_active=True)
            .with_pair_count()
            .filter(pair_count__gte=self.model.MIN_PAIRS)
            .order_by("order", "id")
        )


class MatchPairsStage(models.Model):
    """
    Một chặng của Ghép cặp. Nội dung biên tập tay, không cắt từ kho từ vựng chung:
    một ván cần các từ tiếng Anh phân biệt *và* các nghĩa tiếng Việt phân biệt, điều
    mà lát cắt từ vựng theo tần suất không bảo đảm được.
    """

    MIN_PAIRS = 12

    code = models.SlugField(max_length=48, unique=True)
    title_vi = models.CharField(max_length=64)
    subtitle_vi = models.CharField(max_length=96, blank=True)
    symbol = models.CharField(max_length=4, blank=True)  # ✦ ◈ ➜ — vẽ ở mặt sau thẻ
    level = models.CharField(max_length=2, choices=CEFR.choices, default=CEFR.A1)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    objects = MatchPairsStageQuerySet.as_manager()

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return str(self.title_vi)


class MatchPairsWord(models.Model):
    """Một cặp Anh–Việt thuộc một chặng."""

    stage = models.ForeignKey(MatchPairsStage, on_delete=models.CASCADE, related_name="pairs")
    order = models.PositiveSmallIntegerField(default=0)
    english = models.CharField(max_length=48)
    vietnamese = models.CharField(max_length=64)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["stage", "english"], name="uniq_stage_english"),
            models.UniqueConstraint(fields=["stage", "vietnamese"], name="uniq_stage_vietnamese"),
        ]

    def __str__(self) -> str:
        return f"{self.english} · {self.vietnamese}"


class MatchPairsProgress(models.Model):
    """Sao của một (người dùng, chặng, độ khó). Chỉ nâng, không hạ."""

    class Difficulty(models.TextChoices):
        EASY = "easy", "Dễ"
        MEDIUM = "medium", "Trung bình"
        HARD = "hard", "Khó"
        EXPERT = "expert", "Siêu cấp"

    _PAIRS = {"easy": 6, "medium": 8, "hard": 10, "expert": 12}
    MAX_MOVES = 32767  # trần của PositiveSmallIntegerField `best_moves`; vượt là 422, không phải 500

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="match_pairs_progress")
    stage = models.ForeignKey(MatchPairsStage, on_delete=models.CASCADE, related_name="progress")
    difficulty = models.CharField(max_length=6, choices=Difficulty.choices)
    stars = models.PositiveSmallIntegerField(default=0)  # 1..3
    best_moves = models.PositiveSmallIntegerField(default=0)
    play_count = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "stage", "difficulty"], name="uniq_user_stage_difficulty"
            )
        ]
        indexes = [models.Index(fields=["user", "stage"], name="mpp_user_stage_idx")]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.stage_id} · {self.difficulty} · {self.stars}★"

    @classmethod
    def pairs_for(cls, difficulty: str) -> int:
        return cls._PAIRS[str(difficulty)]

    @classmethod
    def thresholds_for(cls, difficulty: str) -> tuple[int, int]:
        """(mốc 3 sao, mốc 2 sao) — tỉ lệ thuận số cặp; 12 cặp giữ đúng 15/21 client đang dùng."""
        pairs = cls.pairs_for(difficulty)
        return math.ceil(pairs * 1.25), math.ceil(pairs * 1.75)

    @classmethod
    def stars_for(cls, difficulty: str, moves: int) -> int:
        three, two = cls.thresholds_for(difficulty)
        if moves <= three:
            return 3
        if moves <= two:
            return 2
        return 1
