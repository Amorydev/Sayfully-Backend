from django.db import models
from django.db.models import Q

from apps.accounts.models import User
from apps.common.models import CEFR
from apps.content.models import Lesson, Unit, Vocabulary


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
