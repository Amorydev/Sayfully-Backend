from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from apps.common.models import CEFR, TimeStampedModel


class Level(models.Model):
    code = models.CharField(max_length=2, primary_key=True, choices=CEFR.choices)
    name_vi = models.CharField(max_length=64)
    tier_label = models.CharField(max_length=64, blank=True)  # nhãn tier: "Bắt đầu nền tảng"
    description_vi = models.CharField(max_length=255, blank=True)
    order = models.PositiveSmallIntegerField()
    word_target = models.PositiveIntegerField(default=600)
    is_free = models.BooleanField(default=False)  # chỉ A1 = True

    def __str__(self) -> str:
        return f"{self.code} · {self.name_vi}"


class Topic(models.Model):
    code = models.SlugField(max_length=48, unique=True)
    name_vi = models.CharField(max_length=64)
    name_en = models.CharField(max_length=64)
    icon = models.CharField(max_length=48, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    def __str__(self) -> str:
        return str(self.name_vi)


class Unit(models.Model):
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name="units")
    order = models.PositiveSmallIntegerField()
    code = models.SlugField(max_length=64)
    title_vi = models.CharField(max_length=128)
    title_en = models.CharField(max_length=128)
    subtitle = models.CharField(max_length=128, blank=True)  # tagline EN cho node lộ trình
    description_vi = models.CharField(max_length=255, blank=True)
    reward = models.JSONField(
        default=dict, blank=True
    )  # rương: {"coins": 150, "badge_code": "..."}

    class Meta:
        constraints = [models.UniqueConstraint(fields=["level", "order"], name="uniq_unit_order")]
        ordering = ["level__order", "order"]

    def __str__(self) -> str:
        return f"{self.level_id} · {self.order}. {self.title_vi}"


class LevelMilestone(models.Model):
    """Chứng chỉ/cột mốc theo cấp — hoàn thành N bài để mở thưởng (rương)."""

    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name="milestones")
    order = models.PositiveSmallIntegerField()
    code = models.SlugField(max_length=32)  # "a1-1"
    name = models.CharField(max_length=32)  # "A1.1"
    title_vi = models.CharField(max_length=128)  # "Chứng chỉ Milestone A1.1"
    requirement_lessons = models.PositiveSmallIntegerField()  # số bài cần hoàn thành
    reward_xp = models.PositiveSmallIntegerField(default=0)
    reward_coins = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["level", "order"], name="uniq_milestone_order")
        ]
        ordering = ["level__order", "order"]

    def __str__(self) -> str:
        return f"{self.level_id} · {self.name}"


class Lesson(models.Model):
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="lessons")
    order = models.PositiveSmallIntegerField()
    code = models.SlugField(max_length=80, unique=True)
    title_vi = models.CharField(max_length=128)
    title_en = models.CharField(max_length=128)
    description_vi = models.TextField(blank=True)
    est_minutes = models.PositiveSmallIntegerField(default=12)
    xp_reward = models.PositiveSmallIntegerField(default=50)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["unit", "order"], name="uniq_lesson_order")]
        ordering = ["unit", "order"]

    def __str__(self) -> str:
        return str(self.code)


class Vocabulary(TimeStampedModel):
    class POS(models.TextChoices):
        NOUN = "n", "Danh từ"
        VERB = "v", "Động từ"
        ADJ = "adj", "Tính từ"
        ADV = "adv", "Trạng từ"
        PREP = "prep", "Giới từ"
        PRON = "pron", "Đại từ"
        CONJ = "conj", "Liên từ"
        DET = "det", "Từ hạn định"
        EXCL = "excl", "Thán từ"

    headword = models.CharField(max_length=64)
    pos = models.CharField(max_length=6, choices=POS.choices)
    level = models.ForeignKey(Level, on_delete=models.PROTECT, related_name="vocabulary")

    meaning_vi = models.CharField(max_length=255)
    definition_en = models.TextField(blank=True)

    # --- Phiên âm: nuôi trực tiếp tính năng tô màu trọng âm trên UI ---
    ipa_uk = models.CharField(max_length=64, blank=True)  # /ˈbjuːtɪfəl/
    ipa_us = models.CharField(max_length=64, blank=True)
    syllables = ArrayField(
        models.CharField(max_length=16), default=list, blank=True
    )  # ['beau','ti','ful']
    ipa_syllables = ArrayField(
        models.CharField(max_length=16), default=list, blank=True
    )  # ['ˈbjuː','tɪ','fəl']
    primary_stress = models.SmallIntegerField(null=True, blank=True)  # index trong mảng
    secondary_stress = models.SmallIntegerField(null=True, blank=True)

    audio_uk_path = models.CharField(max_length=255, blank=True)
    audio_us_path = models.CharField(max_length=255, blank=True)

    frequency_rank = models.IntegerField(null=True, blank=True)  # Oxford 3000/5000
    synonyms = models.JSONField(default=list, blank=True)  # ["household", "folks"]
    topics = models.ManyToManyField(Topic, blank=True, related_name="vocabulary")
    word_family = models.ManyToManyField("self", blank=True, symmetrical=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["headword", "pos"], name="uniq_headword_pos")
        ]
        indexes = [
            models.Index(fields=["level", "frequency_rank"], name="vocab_level_freq_idx"),
            GinIndex(
                fields=["headword"], name="vocab_headword_trgm", opclasses=["gin_trgm_ops"]
            ),  # tra từ điển kiểu 'chứa'
        ]

    def __str__(self) -> str:
        return f"{self.headword} ({self.pos})"


class VocabularyExample(models.Model):
    vocabulary = models.ForeignKey(Vocabulary, on_delete=models.CASCADE, related_name="examples")
    order = models.PositiveSmallIntegerField(default=0)
    text_en = models.CharField(max_length=255)
    text_vi = models.CharField(max_length=255)
    audio_path = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return str(self.text_en)


class Collocation(models.Model):
    vocabulary = models.ForeignKey(
        Vocabulary, on_delete=models.CASCADE, related_name="collocations"
    )
    text_en = models.CharField(max_length=128)
    meaning_vi = models.CharField(max_length=128, blank=True)

    def __str__(self) -> str:
        return str(self.text_en)


class GrammarPoint(models.Model):
    level = models.ForeignKey(Level, on_delete=models.PROTECT, related_name="grammar_points")
    order = models.PositiveSmallIntegerField()
    category = models.CharField(max_length=48, blank=True)  # Thì / Mạo từ / Đại từ...
    title_vi = models.CharField(max_length=160)
    title_en = models.CharField(max_length=160, blank=True)
    formula = models.CharField(max_length=160, blank=True)  # "I + am + [tên]"
    explanation_vi = models.TextField()
    common_mistake_vi = models.TextField(blank=True)  # card amber trong UI
    conjugation = models.JSONField(
        default=list, blank=True
    )  # bảng chia: [{"subject": "I", "form": "am"}, ...]

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["level", "order"], name="uniq_grammar_order")
        ]

    def __str__(self) -> str:
        return str(self.title_vi)


class GrammarExample(models.Model):
    grammar_point = models.ForeignKey(
        GrammarPoint, on_delete=models.CASCADE, related_name="examples"
    )
    order = models.PositiveSmallIntegerField(default=0)
    text_en = models.CharField(max_length=255)
    ipa = models.CharField(max_length=255, blank=True)  # IPA cả câu (G3 sinh)
    text_vi = models.CharField(max_length=255)
    audio_path = models.CharField(max_length=255, blank=True)

    def __str__(self) -> str:
        return str(self.text_en)


class Dialogue(models.Model):
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name="dialogues", null=True, blank=True
    )
    title_en = models.CharField(max_length=128)
    title_vi = models.CharField(max_length=128, blank=True)
    context_vi = models.CharField(max_length=255, blank=True)

    def __str__(self) -> str:
        return str(self.title_en)


class DialogueLine(models.Model):
    dialogue = models.ForeignKey(Dialogue, on_delete=models.CASCADE, related_name="lines")
    order = models.PositiveSmallIntegerField()
    speaker = models.CharField(max_length=32)
    is_native = models.BooleanField(default=False)  # bản xứ vs học viên
    text_en = models.CharField(max_length=255)
    ipa = models.CharField(max_length=255, blank=True)  # IPA cả câu (G3 sinh)
    text_vi = models.CharField(max_length=255)
    audio_path = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return f"{self.speaker}: {self.text_en}"


class LessonStep(models.Model):
    """Playlist có thứ tự của 1 bài học. FK thật => giữ toàn vẹn tham chiếu."""

    class Kind(models.TextChoices):
        INTRO = "intro", "Giới thiệu"
        VOCAB = "vocab", "Từ vựng"
        GRAMMAR = "grammar", "Ngữ pháp"
        DIALOGUE = "dialogue", "Hội thoại"
        SPELLING = "spelling", "Luyện viết"
        QUIZ = "quiz", "Luyện tập"
        WRITING = "writing", "Viết câu (AI)"  # forward-compat; bundle bỏ khi AI tắt

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=12, choices=Kind.choices)

    vocabulary = models.ForeignKey(Vocabulary, null=True, blank=True, on_delete=models.CASCADE)
    grammar_point = models.ForeignKey(GrammarPoint, null=True, blank=True, on_delete=models.CASCADE)
    dialogue = models.ForeignKey(Dialogue, null=True, blank=True, on_delete=models.CASCADE)
    payload = models.JSONField(default=dict, blank=True)  # cấu hình quiz, text intro

    class Meta:
        constraints = [models.UniqueConstraint(fields=["lesson", "order"], name="uniq_step_order")]
        ordering = ["order"]
        indexes = [models.Index(fields=["lesson", "kind"], name="step_lesson_kind_idx")]

    def __str__(self) -> str:
        return f"{self.lesson_id} · bước {self.order} · {self.kind}"


class Reading(models.Model):
    level = models.ForeignKey(Level, on_delete=models.PROTECT, related_name="readings")
    order = models.PositiveSmallIntegerField()
    title_en = models.CharField(max_length=128)
    title_vi = models.CharField(max_length=128)
    topic = models.ForeignKey(Topic, null=True, blank=True, on_delete=models.SET_NULL)
    est_minutes = models.PositiveSmallIntegerField(default=2)
    cover_path = models.CharField(max_length=255, blank=True)
    keywords = models.ManyToManyField(Vocabulary, blank=True, related_name="readings")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["level", "order"], name="uniq_reading_order")
        ]

    def __str__(self) -> str:
        return str(self.title_en)


class ReadingSentence(models.Model):
    reading = models.ForeignKey(Reading, on_delete=models.CASCADE, related_name="sentences")
    order = models.PositiveSmallIntegerField()
    text_en = models.CharField(max_length=512)
    text_vi = models.CharField(max_length=512)
    ipa = models.CharField(max_length=512, blank=True)
    audio_path = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return str(self.text_en)


class ReadingQuestion(models.Model):
    reading = models.ForeignKey(Reading, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveSmallIntegerField()
    question_en = models.CharField(max_length=512)
    options = models.JSONField()  # ["A","B","C","D"]
    answer_index = models.PositiveSmallIntegerField()
    explanation_vi = models.CharField(max_length=512, blank=True)

    def __str__(self) -> str:
        return str(self.question_en)


class Story(models.Model):
    level = models.ForeignKey(Level, on_delete=models.PROTECT, related_name="stories")
    order = models.PositiveSmallIntegerField()
    title_en = models.CharField(max_length=128)
    title_vi = models.CharField(max_length=128)
    genre = models.CharField(max_length=48, blank=True)
    synopsis_vi = models.CharField(max_length=512, blank=True)
    cover_path = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["level", "order"], name="uniq_story_order")]

    def __str__(self) -> str:
        return str(self.title_en)


class StoryScene(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="scenes")
    order = models.PositiveSmallIntegerField()
    illustration_path = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return f"{self.story_id} · cảnh {self.order}"


class StorySentence(models.Model):
    scene = models.ForeignKey(StoryScene, on_delete=models.CASCADE, related_name="sentences")
    order = models.PositiveSmallIntegerField()
    text_en = models.CharField(max_length=512)
    text_vi = models.CharField(max_length=512)
    audio_path = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return str(self.text_en)


class StoryQuestion(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveSmallIntegerField()
    question_en = models.CharField(max_length=512)
    options = models.JSONField()
    answer_index = models.PositiveSmallIntegerField()
    explanation_vi = models.CharField(max_length=512, blank=True)

    def __str__(self) -> str:
        return str(self.question_en)


class Video(models.Model):
    level = models.ForeignKey(Level, on_delete=models.PROTECT, related_name="videos")
    youtube_id = models.CharField(max_length=24, unique=True)
    title_vi = models.CharField(max_length=160)
    title_en = models.CharField(max_length=160)
    category = models.CharField(max_length=48, blank=True)
    duration_sec = models.PositiveIntegerField(default=0)
    thumbnail_path = models.CharField(max_length=255, blank=True)
    is_free = models.BooleanField(default=True)

    def __str__(self) -> str:
        return str(self.title_vi)


class VideoSubtitle(models.Model):
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="subtitles")
    order = models.PositiveIntegerField()
    start_ms = models.PositiveIntegerField()
    end_ms = models.PositiveIntegerField()
    text_en = models.CharField(max_length=512)
    ipa = models.CharField(max_length=512, blank=True)
    text_vi = models.CharField(max_length=512)

    class Meta:
        ordering = ["order"]
        indexes = [models.Index(fields=["video", "start_ms"], name="sub_video_time_idx")]

    def __str__(self) -> str:
        return str(self.text_en)


class WordRoot(models.Model):
    class Kind(models.TextChoices):
        PREFIX = "prefix", "Tiền tố"
        ROOT = "root", "Gốc từ"
        SUFFIX = "suffix", "Hậu tố"

    kind = models.CharField(max_length=8, choices=Kind.choices)
    text = models.CharField(max_length=32)  # "un-"
    meaning_vi = models.CharField(max_length=128)
    group_vi = models.CharField(max_length=64, blank=True)  # "Phủ định"
    mnemonic_vi = models.TextField(blank=True)
    examples = models.ManyToManyField(Vocabulary, blank=True, related_name="roots")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["kind", "text"], name="uniq_root")]

    def __str__(self) -> str:
        return str(self.text)


class PhrasalVerb(models.Model):
    verb_group = models.CharField(max_length=16)  # "get"
    text = models.CharField(max_length=48, unique=True)  # "get up"
    ipa = models.CharField(max_length=64, blank=True)
    meaning_vi = models.CharField(max_length=160)
    explanation_vi = models.TextField(blank=True)
    examples = models.JSONField(default=list, blank=True)  # [{en, vi, audio_path}]
    level = models.ForeignKey(Level, on_delete=models.PROTECT, related_name="phrasal_verbs")

    class Meta:
        indexes = [models.Index(fields=["verb_group"], name="pv_group_idx")]

    def __str__(self) -> str:
        return str(self.text)


class IPASound(models.Model):
    class Kind(models.TextChoices):
        VOWEL = "vowel", "Nguyên âm"
        CONSONANT = "consonant", "Phụ âm"

    symbol = models.CharField(max_length=8, unique=True)  # "iː"
    kind = models.CharField(max_length=10, choices=Kind.choices)
    description_vi = models.CharField(max_length=255)
    articulation_vi = models.TextField(blank=True)  # khẩu hình chi tiết: môi/lưỡi/hơi
    mouth_image_path = models.CharField(max_length=255, blank=True)
    sample_words = models.JSONField(default=list)  # ["sheep","see","tea"]
    minimal_pair = models.JSONField(
        default=dict, blank=True
    )  # {"other":"ɪ","words":["sheep","ship"]}
    audio_uk_path = models.CharField(max_length=255, blank=True)
    audio_us_path = models.CharField(max_length=255, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    def __str__(self) -> str:
        return str(self.symbol)


class ShadowingDeck(models.Model):
    level = models.ForeignKey(Level, on_delete=models.PROTECT, related_name="shadowing_decks")
    order = models.PositiveSmallIntegerField()
    title_en = models.CharField(max_length=128)
    title_vi = models.CharField(max_length=128, blank=True)
    focus_vi = models.CharField(max_length=128, blank=True)  # "Âm /æ/ & ngữ điệu cảm thán"
    est_seconds = models.PositiveIntegerField(default=0)
    is_free = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["level", "order"], name="uniq_shadowing_order")
        ]

    def __str__(self) -> str:
        return str(self.title_en)


class ShadowingSentence(models.Model):
    deck = models.ForeignKey(ShadowingDeck, on_delete=models.CASCADE, related_name="sentences")
    order = models.PositiveSmallIntegerField()
    text_en = models.CharField(max_length=512)
    ipa = models.CharField(max_length=512, blank=True)
    text_vi = models.CharField(max_length=512)
    audio_path = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return str(self.text_en)


class ContentBundle(models.Model):
    """Bản đóng gói JSON tĩnh của 1 cấp trên CDN (G5). Manifest ghép từ các dòng này."""

    level = models.OneToOneField(Level, on_delete=models.CASCADE, related_name="bundle")
    version = models.PositiveIntegerField(default=1)
    url = models.CharField(max_length=255)
    checksum = models.CharField(max_length=64)  # sha256 hex
    size = models.PositiveIntegerField(default=0)
    built_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.level_id} v{self.version}"
