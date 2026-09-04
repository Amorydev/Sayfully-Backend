from django.db import models

from apps.accounts.models import User


class Exam(models.Model):
    class Type(models.TextChoices):
        IELTS = "ielts", "IELTS"
        TOEIC = "toeic", "TOEIC"
        TOEFL = "toefl", "TOEFL"

    class Difficulty(models.TextChoices):
        EASY = "easy", "Dễ"
        MEDIUM = "medium", "Trung bình"
        HARD = "hard", "Khó"

    exam_type = models.CharField(max_length=8, choices=Type.choices)
    band_group = models.CharField(max_length=16)  # "4.0-5.0" | "450-600"
    difficulty = models.CharField(max_length=8, choices=Difficulty.choices)
    code = models.SlugField(max_length=64, unique=True)
    title_vi = models.CharField(max_length=128)
    duration_min = models.PositiveSmallIntegerField(default=60)
    total_questions = models.PositiveSmallIntegerField(default=40)
    pass_score = models.PositiveSmallIntegerField(default=50)
    max_score = models.PositiveSmallIntegerField(default=100)
    is_free = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["exam_type", "band_group", "difficulty"], name="exam_filter_idx")
        ]

    def __str__(self) -> str:
        return str(self.code)


class ExamSection(models.Model):
    class Kind(models.TextChoices):
        LISTENING = "listening", "Nghe"
        READING = "reading", "Đọc"

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="sections")
    order = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=10, choices=Kind.choices)
    title = models.CharField(max_length=64, blank=True)
    instruction_vi = models.CharField(max_length=512, blank=True)
    passage_en = models.TextField(blank=True)  # cho phần Reading

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return f"{self.exam_id} · {self.kind}"


class ExamQuestion(models.Model):
    class QType(models.TextChoices):
        SINGLE = "single", "Trắc nghiệm"
        TRUE_FALSE = "tf", "Đúng/Sai"
        FILL = "fill", "Điền từ"
        MATCH = "match", "Nối"

    section = models.ForeignKey(ExamSection, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveSmallIntegerField()
    qtype = models.CharField(max_length=8, choices=QType.choices, default=QType.SINGLE)
    prompt_en = models.CharField(max_length=512)
    audio_path = models.CharField(max_length=255, blank=True)
    image_path = models.CharField(max_length=255, blank=True)
    options = models.JSONField(default=list, blank=True)
    answer = models.JSONField()  # index | text | mapping
    explanation_vi = models.CharField(max_length=512, blank=True)
    points = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(fields=["section", "order"], name="uniq_examq_order")
        ]

    def __str__(self) -> str:
        return f"{self.section_id} · câu {self.order}"


class ExamAttempt(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="exam_attempts")
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="attempts")
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.PositiveSmallIntegerField(default=0)
    band_result = models.CharField(max_length=8, blank=True)  # "5.5"
    section_scores = models.JSONField(default=dict, blank=True)  # {"listening":6.0,"reading":5.0}
    time_spent_sec = models.PositiveIntegerField(default=0)
    is_passed = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-submitted_at"], name="attempt_user_recent_idx"),
            models.Index(fields=["user", "exam"], name="attempt_user_exam_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.exam_id} · {self.score}"


class ExamAnswer(models.Model):
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(ExamQuestion, on_delete=models.CASCADE)
    answer = models.JSONField(null=True, blank=True)
    is_correct = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["attempt", "question"], name="uniq_attempt_q")
        ]

    def __str__(self) -> str:
        return f"{self.attempt_id} · câu {self.question_id}"
