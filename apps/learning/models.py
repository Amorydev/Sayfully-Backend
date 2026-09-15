from django.db import models
from django.db.models import Q

from apps.accounts.models import User
from apps.common.models import CEFR
from apps.content.models import (
    GrammarPoint,
    IPASound,
    Lesson,
    ListeningTopic,
    Reading,
    ShadowingDeck,
    Unit,
    Vocabulary,
    VocabularyDeck,
    WordRoot,
)


class LessonProgress(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "Đang học"
        COMPLETED = "completed", "Hoàn thành"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="lesson_progress")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="progress")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.IN_PROGRESS)
    step_index = models.PositiveSmallIntegerField(default=0)
    correct_count = models.PositiveSmallIntegerField(default=0)
    total_questions = models.PositiveSmallIntegerField(default=0)
    stars = models.PositiveSmallIntegerField(default=0)
    xp_earned = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "lesson"], name="uniq_user_lesson")]
        indexes = [
            models.Index(
                fields=["user", "-updated_at"], name="lp_user_recent_idx"
            ),  # "Tiếp tục học"
        ]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.lesson_id} · {self.status}"


class SRSCard(models.Model):
    """FSRS. Bảng LỚN NHẤT hệ thống — mọi quyết định index xoay quanh nó."""

    class State(models.IntegerChoices):
        NEW = 0, "Mới"
        LEARNING = 1, "Đang học"
        REVIEW = 2, "Ôn tập"
        RELEARNING = 3, "Học lại"
        SUSPENDED = 4, "Tạm dừng"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="srs_cards")
    vocabulary = models.ForeignKey(Vocabulary, on_delete=models.CASCADE, related_name="srs_cards")

    state = models.SmallIntegerField(choices=State.choices, default=State.NEW)
    due_at = models.DateTimeField()
    stability = models.FloatField(default=0)  # S của FSRS
    difficulty = models.FloatField(default=0)  # D của FSRS
    fsrs_step = models.PositiveSmallIntegerField(default=0)  # bước học FSRS
    reps = models.PositiveIntegerField(default=0)
    lapses = models.PositiveIntegerField(default=0)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "vocabulary"], name="uniq_srs_card")]
        indexes = [
            # ⭐ INDEX QUAN TRỌNG NHẤT: "lấy 20 từ đến hạn của user X"
            models.Index(
                fields=["user", "due_at"], name="srs_due_idx", condition=~Q(state=4)
            ),  # bỏ thẻ suspended
            models.Index(fields=["user", "state"], name="srs_user_state_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.vocabulary_id} · due {self.due_at:%Y-%m-%d}"


class SRSReviewLog(models.Model):
    """Nhật ký ôn — dùng để tinh chỉnh tham số FSRS. Giữ 180 ngày rồi dọn."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="srs_logs")
    vocabulary = models.ForeignKey(Vocabulary, on_delete=models.CASCADE)
    rating = models.SmallIntegerField()  # 1 Quên · 2 Khó · 3 Tốt · 4 Dễ
    state_before = models.SmallIntegerField()
    elapsed_days = models.IntegerField(default=0)
    scheduled_days = models.IntegerField(default=0)
    reviewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "reviewed_at"], name="srslog_user_time_idx")]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.vocabulary_id} · rating {self.rating}"


class NotebookEntry(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notebook")
    vocabulary = models.ForeignKey(Vocabulary, null=True, blank=True, on_delete=models.CASCADE)
    custom_word = models.CharField(max_length=64, blank=True)  # từ tự nhập
    custom_meaning = models.CharField(max_length=255, blank=True)
    note = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "vocabulary"],
                condition=Q(vocabulary__isnull=False),
                name="uniq_notebook_vocab",
            ),
        ]
        indexes = [models.Index(fields=["user", "-created_at"], name="nb_user_recent_idx")]

    def __str__(self) -> str:
        return self.custom_word or f"vocab {self.vocabulary_id}"


class DailyActivity(models.Model):
    """1 dòng/user/ngày. Nguồn sự thật cho streak, lịch, biểu đồ, tổng hợp tuần."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="daily_activity")
    date = models.DateField()  # theo timezone của user
    xp = models.PositiveIntegerField(default=0)
    lessons_completed = models.PositiveSmallIntegerField(default=0)
    words_reviewed = models.PositiveIntegerField(default=0)
    speaking_count = models.PositiveSmallIntegerField(default=0)
    listening_count = models.PositiveSmallIntegerField(default=0)
    ai_turns = models.PositiveSmallIntegerField(default=0)  # lượt nói với Gia sư AI
    minutes = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "date"], name="uniq_daily")]
        indexes = [
            models.Index(fields=["user", "-date"], name="daily_user_date_idx"),
            models.Index(fields=["date"], name="daily_date_idx"),  # job tổng hợp tuần
        ]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.date}"


class WeeklyStat(models.Model):
    """Tổng hợp sẵn cho bảng xếp hạng toàn cầu — tránh SUM() mỗi lần mở màn."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="weekly_stats")
    iso_year = models.PositiveSmallIntegerField()
    iso_week = models.PositiveSmallIntegerField()
    xp = models.PositiveIntegerField(default=0)
    days_active = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "iso_year", "iso_week"], name="uniq_weekly")
        ]
        indexes = [
            # ⭐ Bảng xếp hạng tuần: quét index, không sort toàn bảng
            models.Index(fields=["iso_year", "iso_week", "-xp"], name="weekly_rank_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.iso_year}-W{self.iso_week:02d}"


class UserSkill(models.Model):
    class Kind(models.TextChoices):
        SPEAKING = "speaking", "Nói"
        LISTENING = "listening", "Nghe"
        READING = "reading", "Đọc"
        WRITING = "writing", "Viết"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="skills")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    xp = models.PositiveIntegerField(default=0)
    level = models.PositiveSmallIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "kind"], name="uniq_user_skill")]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.kind} · Lv{self.level}"


class IPASoundProgress(models.Model):
    """Tiến độ luyện từng âm IPA (C43). Thuần thục khi điểm tốt nhất ≥ MASTERY_SCORE."""

    MASTERY_SCORE = 80

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ipa_progress")
    sound = models.ForeignKey(IPASound, on_delete=models.CASCADE, related_name="progress")
    best_score = models.PositiveSmallIntegerField(default=0)
    attempts = models.PositiveIntegerField(default=0)
    mastered_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "sound"], name="uniq_user_ipa_sound")
        ]

    def __str__(self) -> str:
        return f"{self.user_id} · /{self.sound.symbol}/ · {self.best_score}"


class WordRootProgress(models.Model):
    LEARNED_PERCENT = 70

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="root_progress")
    root = models.ForeignKey(WordRoot, on_delete=models.CASCADE, related_name="progress")
    best_percent = models.PositiveSmallIntegerField(default=0)
    attempts = models.PositiveIntegerField(default=0)
    learned_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "root"], name="uniq_user_word_root")]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.root.text} · {self.best_percent}%"


class GrammarProgress(models.Model):
    COMPLETE_PERCENT = 70
    XP_REWARD = 30

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="grammar_progress")
    grammar_point = models.ForeignKey(
        GrammarPoint, on_delete=models.CASCADE, related_name="progress"
    )
    best_percent = models.PositiveSmallIntegerField(default=0)
    attempts = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "grammar_point"], name="uniq_user_grammar_point"
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.grammar_point_id} · {self.best_percent}%"


class PlacementQuestion(models.Model):
    """Bài kiểm tra xếp lớp 3 phút (C23) — ~12 câu, không thuộc đề thi nào."""

    class Skill(models.TextChoices):
        VOCAB = "vocab", "Từ vựng"
        GRAMMAR = "grammar", "Ngữ pháp"
        LISTENING = "listening", "Nghe"

    order = models.PositiveSmallIntegerField(unique=True)
    skill = models.CharField(max_length=10, choices=Skill.choices)
    level = models.CharField(max_length=2, choices=CEFR.choices)  # câu này đo cấp nào
    prompt_en = models.CharField(max_length=512)
    options = models.JSONField()  # ["go","goes","going","went"]
    answer_index = models.PositiveSmallIntegerField()
    audio_path = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return f"{self.order}. {self.prompt_en[:40]}"


class PlacementAttempt(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="placement_attempts")
    answers = models.JSONField()  # {question_id: chosen_index}
    score_by_skill = models.JSONField(default=dict)  # {"vocab": 7, "grammar": 5, "listening": 6}
    suggested_level = models.CharField(max_length=2, choices=CEFR.choices)
    suggested_unit = models.ForeignKey(Unit, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "-created_at"], name="placement_user_idx")]

    def __str__(self) -> str:
        return f"{self.user_id} → {self.suggested_level}"


class SpeakingTopicProgress(models.Model):
    """Tiến độ luyện nói theo chủ đề (mỗi ShadowingDeck = 1 chủ đề) — hiển thị 'x/y' ở C8a."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="speaking_topic_progress")
    deck = models.ForeignKey(ShadowingDeck, on_delete=models.CASCADE, related_name="topic_progress")
    done_count = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "deck"], name="uniq_speaking_topic_progress")
        ]

    def __str__(self) -> str:
        return f"{self.user_id} · deck{self.deck_id} · {self.done_count}"


class ListeningTopicProgress(models.Model):
    """Tiến độ luyện nghe theo chủ đề & mode (C9a) — 'x/y câu' cho mode đang chọn."""

    class Mode(models.TextChoices):
        CHOOSE = "choose", "Chọn từ"
        DICTATION = "dictation", "Chép chính tả"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="listening_topic_progress"
    )
    topic = models.ForeignKey(
        ListeningTopic, on_delete=models.CASCADE, related_name="topic_progress"
    )
    mode = models.CharField(max_length=10, choices=Mode.choices)
    done_count = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "topic", "mode"], name="uniq_listening_topic_progress"
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_id} · topic{self.topic_id} · {self.mode} · {self.done_count}"


class ReadingProgress(models.Model):
    """Tiến độ đọc theo bài: trạng thái, số câu đã làm và phần thưởng chỉ nhận một lần."""

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "Đang đọc"
        COMPLETED = "completed", "Hoàn thành"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reading_progress")
    reading = models.ForeignKey(Reading, on_delete=models.CASCADE, related_name="reading_progress")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)
    answered_count = models.PositiveSmallIntegerField(default=0)
    correct_count = models.PositiveSmallIntegerField(default=0)
    xp_earned = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "reading"], name="uniq_reading_progress")
        ]
        indexes = [
            models.Index(fields=["user", "status"], name="readprog_user_status_idx"),
            models.Index(fields=["user", "-last_read_at"], name="readprog_user_recent_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} · reading{self.reading_id} · {self.status}"


class ReadingDailyActivity(models.Model):
    """Nguồn sự thật cho chuỗi ngày đọc; một hàng cho mỗi user/ngày theo timezone hồ sơ."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reading_daily_activity")
    date = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "date"], name="uniq_reading_daily_activity")
        ]
        indexes = [models.Index(fields=["user", "-date"], name="readact_user_date_idx")]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.date.isoformat()}"


class VocabularyDeckProgress(models.Model):
    """Người dùng đã mở bộ thẻ nào (C7a) — nuôi thẻ "Đang học" và đếm số học viên của bộ."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="deck_progress")
    deck = models.ForeignKey(VocabularyDeck, on_delete=models.CASCADE, related_name="progress")
    learned_count = models.PositiveIntegerField(default=0)  # số thẻ đã thuộc trong bộ
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "deck"], name="uniq_user_deck_progress")
        ]
        indexes = [models.Index(fields=["user", "-updated_at"], name="deck_prog_recent_idx")]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.deck_id}"
