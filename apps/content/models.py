from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone

from apps.common.models import CEFR, TimeStampedModel


class AccentAudio(models.Model):
    """Audio hai giọng cho một câu/đoạn. `audio_for(accent)` chọn theo `UserProfile.accent`,
    thiếu giọng nào thì lấy giọng còn lại để không "câm"."""

    audio_us_path = models.CharField(max_length=255, blank=True)
    audio_uk_path = models.CharField(max_length=255, blank=True)

    class Meta:
        abstract = True

    def audio_for(self, accent: str) -> str:
        primary, other = (
            (self.audio_us_path, self.audio_uk_path)
            if accent == "US"
            else (self.audio_uk_path, self.audio_us_path)
        )
        return primary or other


class Level(models.Model):
    code = models.CharField(max_length=2, primary_key=True, choices=CEFR.choices)
    name_vi = models.CharField(max_length=64)
    tier_label = models.CharField(max_length=64, blank=True)  # nhãn tier: "Bắt đầu nền tảng"
    description_vi = models.CharField(max_length=255, blank=True)
    order = models.PositiveSmallIntegerField()
    word_target = models.PositiveIntegerField(default=600)
    is_free = models.BooleanField(default=False)  # quyết định cấp này có cần Premium hay không

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


class ContentSource(models.Model):
    """Nguồn dữ liệu khung (EVP, GSE, EGP, CEFR CV, Core Inventory, LFC, VOA…) — trang Attribution
    + audit bản quyền. Seed từ `framework_final.json["sources"]`."""

    code = models.SlugField(max_length=24, primary_key=True)
    name = models.CharField(max_length=200)
    license = models.CharField(max_length=8, blank=True)  # open | cond
    usage = models.CharField(max_length=12, blank=True)  # content | reference | structure
    attribution = models.CharField(max_length=512, blank=True)
    tos_note = models.TextField(blank=True)

    def __str__(self) -> str:
        return str(self.code)


class Band(models.Model):
    """Nửa cấp (A1.1, A2+, B1+…): 10 band, dải GSE để xếp unit/bài; 1 band = 1 LevelMilestone."""

    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name="bands")
    order = models.PositiveSmallIntegerField()  # 1 | 2 trong cấp
    code = models.CharField(max_length=6, unique=True)  # "A1.1", "A2+", "B1+"
    cefr_label = models.CharField(max_length=4)  # nhãn CEFR gốc: A1 | A2 | A2+ | B1 | B1+ …
    gse_min = models.PositiveSmallIntegerField()
    gse_max = models.PositiveSmallIntegerField()
    title_vi = models.CharField(max_length=128)
    milestone = models.OneToOneField(
        "LevelMilestone", null=True, blank=True, on_delete=models.SET_NULL, related_name="band"
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["level", "order"], name="uniq_band_order")]
        ordering = ["level__order", "order"]

    def __str__(self) -> str:
        return str(self.code)


class CanDo(models.Model):
    """Descriptor 'có thể làm gì' — CEFR Companion Volume + GSE learning/grammar objective.
    Nuôi mục tiêu band (BandGoal), mục tiêu bài (LessonObjective) và can-do ngữ pháp."""

    class Source(models.TextChoices):
        CEFR = "cefr", "CEFR Companion Volume"
        GSE_LO = "gse_lo", "GSE Learning Objective"
        GSE_GR = "gse_gr", "GSE Grammar Objective"

    code = models.CharField(max_length=128, unique=True)  # "GLLA0603" | "Conversation#A2#5"
    source = models.CharField(max_length=8, choices=Source.choices)
    level = models.ForeignKey(Level, on_delete=models.PROTECT, related_name="can_dos")
    cefr_label = models.CharField(max_length=6)  # Pre-A1 | A1 | A2 | A2+ … (giữ plus level)
    gse = models.PositiveSmallIntegerField(null=True, blank=True)  # chỉ GSE
    skill = models.CharField(
        max_length=128, blank=True
    )  # GSE: Listening/Speaking…; CEFR: tên thang
    scale = models.CharField(
        max_length=255, blank=True
    )  # CEFR: cột thang; GSE: grammatical_categories
    can_do_vi = models.CharField(max_length=512)
    can_do_en = models.CharField(max_length=512)
    examples = models.JSONField(default=list, blank=True)  # [{en, vi}]
    is_speaking_core = models.BooleanField(default=False)  # 10 thang nói/nghe dùng làm BandGoal

    class Meta:
        indexes = [models.Index(fields=["level", "skill", "gse"], name="cando_level_skill_gse_idx")]

    def __str__(self) -> str:
        return str(self.code)


class BandGoal(models.Model):
    """Mục tiêu hiển thị ở đầu band / màn chứng chỉ: 'Kết thúc A1.1 bạn có thể…'."""

    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name="goals")
    can_do = models.ForeignKey(CanDo, on_delete=models.PROTECT)
    order = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["band", "can_do"], name="uniq_band_cando")]
        ordering = ["order"]

    def __str__(self) -> str:
        return f"{self.band_id} · {self.can_do_id}"


class LanguageFunction(models.Model):
    """Core Inventory: 'Giving personal information', 'Telling the time'… (số thứ tự trong poster)."""

    number = models.PositiveSmallIntegerField(unique=True)
    title_en = models.CharField(max_length=160)
    title_vi = models.CharField(max_length=160, blank=True)
    section = models.CharField(
        max_length=32, blank=True
    )  # functions | grammar | discourse_markers…
    levels = models.JSONField(default=dict, blank=True)  # {"A1": "core", "A2": "partial"}

    def __str__(self) -> str:
        return f"{self.number}. {self.title_en}"


class FunctionExponent(models.Model):
    """Câu mẫu Sayfully viết cho chức năng × level — prompt của bước Speaking."""

    function = models.ForeignKey(
        LanguageFunction, on_delete=models.CASCADE, related_name="exponents"
    )
    level = models.ForeignKey(Level, on_delete=models.PROTECT)
    title_en = models.CharField(max_length=160, blank=True)
    examples = models.JSONField(default=list)  # [{en, vi}]

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["function", "level"], name="uniq_exponent_level")
        ]

    def __str__(self) -> str:
        return f"{self.function_id} · {self.level_id}"


class PronunciationFeature(models.Model):
    """Lingua Franca Core (22 đặc điểm) — trọng tâm phát âm của bài; nối IPASound."""

    code = models.SlugField(max_length=48, unique=True)  # "LFC-C01"
    category_en = models.CharField(max_length=64, blank=True)
    category_vi = models.CharField(max_length=64)
    feature_en = models.CharField(max_length=160)
    status = models.CharField(max_length=10)  # Core | Non-core
    ipa = models.CharField(max_length=96, blank=True)
    rule_en = models.TextField(blank=True)
    rule_vi = models.TextField()
    focus_en = models.TextField(blank=True)
    focus_vi = models.TextField(blank=True)
    examples_en = models.TextField(blank=True)
    examples_vi = models.TextField(blank=True)
    sounds = models.ManyToManyField("IPASound", blank=True, related_name="features")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return f"{self.code} · {self.feature_en}"


class Unit(models.Model):
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name="units")
    band = models.ForeignKey(
        Band, null=True, blank=True, on_delete=models.PROTECT, related_name="units"
    )
    topic = models.ForeignKey(Topic, null=True, blank=True, on_delete=models.SET_NULL)
    function = models.ForeignKey(
        LanguageFunction, null=True, blank=True, on_delete=models.SET_NULL, related_name="units"
    )
    topic_en = models.CharField(max_length=64, blank=True)  # chủ đề Core Inventory (text)
    topic_vi = models.CharField(max_length=64, blank=True)
    gse_min = models.PositiveSmallIntegerField(null=True, blank=True)
    gse_max = models.PositiveSmallIntegerField(null=True, blank=True)
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
    path_subtitle_vi = models.CharField(
        max_length=160,
        blank=True,
        default="",
        help_text="Dòng mô tả ngắn hiển thị trong Unit sheet của lộ trình.",
    )
    est_minutes = models.PositiveSmallIntegerField(default=12)
    xp_reward = models.PositiveSmallIntegerField(default=50)
    # --- lộ trình (PATH-SCHEMA §3.2) ---
    grammar_point = models.ForeignKey(
        "GrammarPoint",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="primary_lessons",
    )
    pronunciation_feature = models.ForeignKey(
        PronunciationFeature,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="lessons",
    )
    speaking_function = models.ForeignKey(
        LanguageFunction, null=True, blank=True, on_delete=models.SET_NULL, related_name="lessons"
    )
    gse = models.PositiveSmallIntegerField(null=True, blank=True)  # median GSE của objectives
    source_ref = models.CharField(
        max_length=32, blank=True
    )  # "voa-l1:lesson-01" nếu dùng hội thoại VOA

    class Meta:
        constraints = [models.UniqueConstraint(fields=["unit", "order"], name="uniq_lesson_order")]
        ordering = ["unit", "order"]

    def __str__(self) -> str:
        return str(self.code)


class LessonObjective(models.Model):
    """2–3 can-do mỗi bài (GSE Speaking/Listening là chính) — màn 'Sau bài này bạn có thể…'."""

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="objectives")
    can_do = models.ForeignKey(CanDo, on_delete=models.PROTECT, related_name="lessons")
    order = models.PositiveSmallIntegerField(default=0)
    is_primary = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lesson", "can_do"], name="uniq_lesson_cando")
        ]
        ordering = ["order"]

    def __str__(self) -> str:
        return f"{self.lesson_id} · {self.can_do_id}"


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
        NUM = "num", "Số từ"
        PHRASE = "phr", "Cụm từ"
        MODAL = "modal", "Động từ khuyết thiếu"
        AUX = "aux", "Trợ động từ"

    headword = models.CharField(max_length=64)
    pos = models.CharField(max_length=6, choices=POS.choices)
    level = models.ForeignKey(Level, on_delete=models.PROTECT, related_name="vocabulary")

    meaning_vi = models.CharField(max_length=255)
    definition_en = models.TextField(blank=True)
    definition_vi = models.TextField(blank=True)

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
    antonyms = models.JSONField(default=list, blank=True)
    topics = models.ManyToManyField(Topic, blank=True, related_name="vocabulary")
    word_family = models.ManyToManyField("self", blank=True, symmetrical=True)
    # --- khung EVP/GSE (PATH-SCHEMA §3.2); 1 headword+pos có thể nhiều nghĩa → thêm `sense` ---
    sense = models.SlugField(
        max_length=64, default="", blank=True
    )  # slug guideword EVP; "" nếu 1 nghĩa
    sense_label_en = models.CharField(max_length=96, blank=True)  # "NOT PARTICULAR"
    headword_us = models.CharField(max_length=64, blank=True)  # "color" khi khác British
    category = models.CharField(
        max_length=16, default="word"
    )  # word | phrase | phrasal_verb | idiom
    gse = models.PositiveSmallIntegerField(null=True, blank=True)
    usage_label = models.CharField(max_length=32, blank=True)
    source = models.ForeignKey(ContentSource, null=True, blank=True, on_delete=models.SET_NULL)
    source_ref = models.CharField(max_length=64, blank=True, db_index=True)  # "ID_00001050_01_UK"
    is_path_core = models.BooleanField(default=False)  # nằm trong lộ trình (≠ chỉ từ điển)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["headword", "pos", "sense"], name="uniq_headword_pos_sense"
            )
        ]
        indexes = [
            models.Index(fields=["level", "frequency_rank"], name="vocab_level_freq_idx"),
            GinIndex(
                fields=["headword"], name="vocab_headword_trgm", opclasses=["gin_trgm_ops"]
            ),  # tra từ điển kiểu 'chứa'
        ]

    def __str__(self) -> str:
        return f"{self.headword} ({self.pos})"


class VocabularyExample(AccentAudio):
    vocabulary = models.ForeignKey(Vocabulary, on_delete=models.CASCADE, related_name="examples")
    order = models.PositiveSmallIntegerField(default=0)
    text_en = models.CharField(max_length=255)
    text_vi = models.CharField(max_length=255)

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
    subtitle_vi = models.CharField(max_length=160, blank=True)  # "Khái niệm cốt lõi · 3 quy tắc"
    form_vi = models.CharField(max_length=96, blank=True)  # "Thể khẳng định · Hiện tại đơn"
    formula = models.CharField(max_length=160, blank=True)  # "S + be + N/Adj"
    formula_parts = models.JSONField(
        default=list, blank=True
    )  # [{"token": "S", "label_vi": "Chủ ngữ"}, {"token": "be", "label_vi": "am / is / are"}]
    note_vi = models.TextField(blank=True)  # ghi nhớ nhanh cạnh công thức
    explanation_vi = models.TextField()
    common_mistake_vi = models.TextField(blank=True)  # card amber trong UI
    mistake_wrong = models.CharField(max_length=160, blank=True)  # "She very beautiful"
    mistake_right = models.CharField(max_length=160, blank=True)  # "She is very beautiful"
    conjugation = models.JSONField(
        default=list, blank=True
    )  # bảng chia: [{"subject": "I", "form": "am"}, ...]
    # --- khung EGP (PATH-SCHEMA §3.2) ---
    source_ref = models.CharField(max_length=16, blank=True, db_index=True)  # EGP id "647"
    super_category = models.CharField(max_length=32, blank=True)  # MODALITY / PAST / CLAUSES…
    sub_category = models.CharField(max_length=96, blank=True)
    guideword_type = models.CharField(max_length=10, blank=True)  # FORM | USE | FORM/USE
    guideword = models.CharField(max_length=200, blank=True)
    lexical_range = models.CharField(max_length=32, blank=True)
    objectives = models.ManyToManyField(CanDo, blank=True, related_name="grammar_points")
    is_path_core = models.BooleanField(default=False)  # 1 điểm chính/bài

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["level", "order"], name="uniq_grammar_order")
        ]

    def __str__(self) -> str:
        return str(self.title_vi)


class GrammarExample(AccentAudio):
    grammar_point = models.ForeignKey(
        GrammarPoint, on_delete=models.CASCADE, related_name="examples"
    )
    order = models.PositiveSmallIntegerField(default=0)
    text_en = models.CharField(max_length=255)
    ipa = models.CharField(max_length=255, blank=True)  # IPA cả câu (G3 sinh)
    text_vi = models.CharField(max_length=255)

    def __str__(self) -> str:
        return str(self.text_en)


class GrammarExercise(models.Model):
    """Câu thực hành trắc nghiệm điền chỗ trống cho một điểm ngữ pháp (C42)."""

    grammar_point = models.ForeignKey(
        GrammarPoint, on_delete=models.CASCADE, related_name="exercises"
    )
    order = models.PositiveSmallIntegerField(default=0)
    prompt_en = models.CharField(max_length=255)  # "She ___ a teacher."
    prompt_vi = models.CharField(max_length=255, blank=True)
    options = models.JSONField(default=list)  # ["am", "is", "are"]
    answer_index = models.PositiveSmallIntegerField(default=0)
    explanation_vi = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return str(self.prompt_en)


class Dialogue(models.Model):
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name="dialogues", null=True, blank=True
    )
    title_en = models.CharField(max_length=128)
    title_vi = models.CharField(max_length=128, blank=True)
    context_vi = models.CharField(max_length=255, blank=True)
    context_en = models.CharField(max_length=255, blank=True)
    source_ref = models.CharField(
        max_length=48, blank=True, db_index=True
    )  # "voa-l1:lesson-01-conv" | "gen:a1-01-hello-3"

    def __str__(self) -> str:
        return str(self.title_en)


class DialogueLine(AccentAudio):
    dialogue = models.ForeignKey(Dialogue, on_delete=models.CASCADE, related_name="lines")
    order = models.PositiveSmallIntegerField()
    speaker = models.CharField(max_length=32)
    is_native = models.BooleanField(default=False)  # bản xứ vs học viên
    text_en = models.CharField(max_length=1024)  # lượt thoại VOA dài tới ~700 ký tự
    ipa = models.CharField(max_length=1024, blank=True)  # IPA cả câu (G3 sinh)
    text_vi = models.CharField(max_length=1024)

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
        SPEAK = "speak", "Nói theo chức năng"  # FunctionExponent (lộ trình)
        PRON = "pron", "Luyện phát âm"  # PronunciationFeature (lộ trình)
        LISTEN = "listen", "Nghe & nhại"  # câu nghe / shadowing (lộ trình)

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


class QuizQuestion(models.Model):
    """Ngân hàng câu hỏi của bài (6 câu/bài, sinh từ crawl/path/build_quiz.py). Bước QUIZ trỏ tới đây qua payload."""

    class Kind(models.TextChoices):
        LISTENING = "listening", "Nghe rồi chọn"  # audio lượt thoại → 4 đáp án
        READING = "reading", "Đọc"
        VOCAB = "vocab", "Nghĩa của từ"  # từ + IPA + loa → 4 nghĩa VI
        CLOZE = "cloze", "Điền từ theo audio"  # sentence_en có ____ → 4 từ
        GRAMMAR = "grammar", "Chọn câu đúng ngữ pháp"  # formula + 4 câu
        REORDER = "reorder", "Sắp xếp từ"  # options = token xáo; đúng khi ghép = sentence_en

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="quiz_questions")
    order = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.LISTENING)
    question_en = models.CharField(max_length=512)
    question_vi = models.CharField(max_length=512, blank=True)
    options = models.JSONField()  # ["…","…","…","…"]
    answer_index = models.PositiveSmallIntegerField()
    explanation_vi = models.CharField(max_length=512, blank=True)
    source_ref = models.CharField(
        max_length=64, blank=True, db_index=True
    )  # "voa-l1:lesson-01#q1" | "genq:…#1"
    audio_us_path = models.CharField(max_length=255, blank=True)
    audio_uk_path = models.CharField(max_length=255, blank=True)
    # Ngữ liệu theo loại: listening = lượt thoại được phát; cloze = câu có ____; reorder = câu đúng; grammar = câu ngữ cảnh (nếu có)
    sentence_en = models.CharField(max_length=512, blank=True, default="")
    sentence_vi = models.CharField(max_length=512, blank=True, default="")
    speaker = models.CharField(max_length=32, blank=True, default="")  # listening: người nói
    hint_vi = models.CharField(max_length=256, blank=True, default="")  # cloze: nghĩa; khác: tên NP
    formula = models.CharField(max_length=128, blank=True, default="")  # công thức điểm ngữ pháp

    class Meta:
        constraints = [models.UniqueConstraint(fields=["lesson", "order"], name="uniq_quiz_order")]
        ordering = ["order"]

    def __str__(self) -> str:
        return str(self.question_en)


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


class ReadingSentence(AccentAudio):
    reading = models.ForeignKey(Reading, on_delete=models.CASCADE, related_name="sentences")
    order = models.PositiveSmallIntegerField()
    text_en = models.CharField(max_length=512)
    text_vi = models.CharField(max_length=512)
    ipa = models.CharField(max_length=512, blank=True)

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


class StorySentence(AccentAudio):
    scene = models.ForeignKey(StoryScene, on_delete=models.CASCADE, related_name="sentences")
    order = models.PositiveSmallIntegerField()
    text_en = models.CharField(max_length=512)
    text_vi = models.CharField(max_length=512)

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
    """Video học. `source=curated` do admin nạp; `source=user` do người dùng Premium dán link
    YouTube — dedupe theo `youtube_id`, ai cũng có thể thêm cùng một video vào thư viện của mình."""

    class Source(models.TextChoices):
        CURATED = "curated", "Sayfully tuyển chọn"
        USER = "user", "Người dùng thêm"

    class Status(models.TextChoices):
        PENDING = "pending", "Chờ xử lý"
        PROCESSING = "processing", "Đang xử lý"
        READY = "ready", "Sẵn sàng"
        FAILED = "failed", "Lỗi"

    # Null với video người dùng cho tới khi LLM ước lượng xong.
    level = models.ForeignKey(
        Level, on_delete=models.PROTECT, related_name="videos", null=True, blank=True
    )
    youtube_id = models.CharField(max_length=24, unique=True)
    title_vi = models.CharField(max_length=160)
    title_en = models.CharField(max_length=160)
    category = models.CharField(max_length=48, blank=True)
    duration_sec = models.PositiveIntegerField(default=0)
    thumbnail_path = models.CharField(max_length=255, blank=True)
    is_free = models.BooleanField(default=True)

    # Hàng "Nổi bật" ở đầu màn Video (cuộn ngang); sắp theo featured_order rồi id.
    is_featured = models.BooleanField(default=False)
    featured_order = models.PositiveSmallIntegerField(default=0)

    source = models.CharField(max_length=8, choices=Source.choices, default=Source.CURATED)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.READY)
    error_code = models.CharField(max_length=32, blank=True)  # no_captions / too_long / ...
    channel = models.CharField(max_length=120, blank=True)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def __str__(self) -> str:
        return str(self.title_vi)


class UserVideoLibrary(models.Model):
    """Video người dùng đã thêm (Premium). Đếm theo ngày để giới hạn lượt import."""

    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="video_library"
    )
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="library_entries")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "video"], name="uniq_user_video")]
        ordering = ["-added_at"]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.video_id}"


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
    group_vi = models.CharField(max_length=64, blank=True)  # "Phủ định & Đối nghịch"
    group_order = models.PositiveSmallIntegerField(default=0)
    order = models.PositiveSmallIntegerField(default=0)
    effect_vi = models.CharField(
        max_length=128, blank=True
    )  # "Biến đổi nghĩa sang đối lập tức thì"
    mnemonic_vi = models.TextField(blank=True)
    # Từ mẫu độc lập với kho từ vựng:
    # [{"word":"unhappy","base":"happy","meaning_vi":"không vui vẻ","ipa":"/ʌnˈhæp.i/",
    #   "audio_us_path":"audio/us/unhappy.mp3","audio_uk_path":"audio/uk/unhappy.mp3"}]
    # Nếu từ có trong kho Vocabulary thì API ưu tiên audio của Vocabulary.
    samples = models.JSONField(default=list, blank=True)
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
    examples = models.JSONField(
        default=list, blank=True
    )  # [{en, vi, audio_us_path, audio_uk_path}]
    level = models.ForeignKey(Level, on_delete=models.PROTECT, related_name="phrasal_verbs")

    class Meta:
        indexes = [models.Index(fields=["verb_group"], name="pv_group_idx")]

    def __str__(self) -> str:
        return str(self.text)


class IPASound(models.Model):
    class Kind(models.TextChoices):
        VOWEL = "vowel", "Nguyên âm"
        CONSONANT = "consonant", "Phụ âm"

    class Group(models.TextChoices):
        MONOPHTHONG = "monophthong", "Nguyên âm đơn"
        DIPHTHONG = "diphthong", "Nguyên âm đôi"
        VOICELESS = "voiceless", "Phụ âm vô thanh"
        VOICED = "voiced", "Phụ âm hữu thanh"
        NASAL_APPROX = "nasal_approx", "Âm mũi & bán nguyên âm"

    symbol = models.CharField(max_length=8, unique=True)  # "iː"
    kind = models.CharField(max_length=10, choices=Kind.choices)
    group = models.CharField(max_length=16, choices=Group.choices, default=Group.MONOPHTHONG)
    category_vi = models.CharField(max_length=64, blank=True)  # "Nguyên âm dài"
    category_en = models.CharField(max_length=64, blank=True)  # "Long Vowel"
    description_vi = models.CharField(max_length=255)
    articulation_vi = models.TextField(blank=True)  # khẩu hình chi tiết: môi/lưỡi/hơi
    lips_vi = models.CharField(max_length=64, blank=True)  # "Bè dẹt"
    tongue_vi = models.CharField(max_length=64, blank=True)  # "Hơi nâng cao"
    tip_vi = models.CharField(max_length=255, blank=True)  # Mẹo từ Bé Rồng
    mouth_image_path = models.CharField(max_length=255, blank=True)
    sample_words = models.JSONField(default=list)  # ["sheep","see","tea"] (từ mẫu ngắn cho ô bảng)
    examples = models.JSONField(
        default=list
    )  # [{"word":"sheep","ipa":"/ʃiːp/","meaning_vi":"con cừu"}]
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
    icon = models.CharField(max_length=48, blank=True)  # token icon dự phòng (map cứng ở app)
    icon_url = models.CharField(
        max_length=255, blank=True
    )  # ảnh icon (URL đầy đủ hoặc path R2) — app render trực tiếp, khỏi rebuild khi thêm chủ đề
    background_url = models.CharField(
        max_length=255, blank=True
    )  # ảnh nền card; URL đầy đủ hoặc path tương đối trên R2
    color = models.CharField(
        max_length=9, blank=True
    )  # màu hex "#22C55E" cho thẻ; rỗng = app tự chọn
    is_free = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["level", "order"], name="uniq_shadowing_order")
        ]

    def __str__(self) -> str:
        return str(self.title_en)


class ShadowingSentence(AccentAudio):
    deck = models.ForeignKey(ShadowingDeck, on_delete=models.CASCADE, related_name="sentences")
    order = models.PositiveSmallIntegerField()
    text_en = models.CharField(max_length=512)
    ipa = models.CharField(max_length=512, blank=True)
    text_vi = models.CharField(max_length=512)
    speaking_goal_vi = models.CharField(max_length=255, blank=True)
    highlights = models.JSONField(
        default=list,
        blank=True,
    )  # [{"text": "meet", "kind": "primary_stress"}]

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return str(self.text_en)


class ListeningTopic(models.Model):
    """Chủ đề luyện nghe (C9a) — mỗi chủ đề gồm nhiều câu nghe, dùng cho cả 2 mode."""

    level = models.ForeignKey(Level, on_delete=models.PROTECT, related_name="listening_topics")
    order = models.PositiveSmallIntegerField()
    title_vi = models.CharField(max_length=128)
    icon = models.CharField(max_length=48, blank=True)  # token icon dự phòng
    icon_url = models.CharField(
        max_length=255, blank=True
    )  # ảnh icon (URL/path) — app render trực tiếp
    color = models.CharField(max_length=9, blank=True)  # màu hex "#RRGGBB" cho thẻ
    est_seconds = models.PositiveIntegerField(default=0)
    is_free = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["level", "order"], name="uniq_listening_topic_order")
        ]
        ordering = ["level__order", "order"]

    def __str__(self) -> str:
        return str(self.title_vi)


class ListeningItem(AccentAudio):
    """1 câu nghe. Mode 'choose' dùng blank_index + options + answer_index (điền chỗ trống);
    mode 'dictation' chỉ cần text_en + audio."""

    topic = models.ForeignKey(ListeningTopic, on_delete=models.CASCADE, related_name="items")
    order = models.PositiveSmallIntegerField()
    text_en = models.CharField(max_length=512)  # câu đầy đủ (đáp án của chỗ trống nằm trong câu)
    text_vi = models.CharField(max_length=512, blank=True)
    blank_index = models.PositiveSmallIntegerField(
        null=True, blank=True
    )  # vị trí từ bị khuyết trong text_en.split() cho mode 'choose'
    options = models.JSONField(default=list, blank=True)  # ["meet", "meat", "mit", "meal"]
    answer_index = models.PositiveSmallIntegerField(null=True, blank=True)  # index đáp án đúng

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


class VocabularyDeckCollection(models.Model):
    """Nhóm bộ thẻ trên màn thư viện flashcard (C7a) — "Bộ sưu tập phổ biến", "Từ vựng Oxford"."""

    code = models.SlugField(max_length=48, unique=True)
    title_vi = models.CharField(max_length=128)
    chip_label_vi = models.CharField(max_length=32, blank=True)  # nhãn chip lọc: "Oxford", "IELTS"
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return str(self.title_vi)


class VocabularyDeck(models.Model):
    """Bộ thẻ flashcard (C7a → C7). Danh sách trả cover + số thẻ + số học viên;
    bấm vào mới gọi endpoint chi tiết lấy toàn bộ thẻ."""

    collection = models.ForeignKey(
        VocabularyDeckCollection, on_delete=models.PROTECT, related_name="decks"
    )
    code = models.SlugField(max_length=64, unique=True)
    title_vi = models.CharField(max_length=128)  # "3000 từ Oxford thông dụng"
    cover_title = models.CharField(max_length=64, blank=True)  # chữ trên cover: "Oxford 3000"
    badge_vi = models.CharField(max_length=32, blank=True)  # nhãn góc cover: "A1 – B2", "Band 7.5+"
    background_url = models.CharField(
        max_length=255, blank=True
    )  # ảnh cover (URL đầy đủ hoặc path R2) — app render trực tiếp
    icon = models.CharField(
        max_length=48, blank=True
    )  # token icon trên cover khi chưa có ảnh: style/book/travel/work/exam/mic/headphones
    accent_color = models.CharField(
        max_length=9, blank=True
    )  # màu nhấn hex "#4F46E5" cho nền cover; rỗng = app dùng indigo mặc định
    level = models.ForeignKey(
        Level, null=True, blank=True, on_delete=models.PROTECT, related_name="vocabulary_decks"
    )
    order = models.PositiveSmallIntegerField(default=0)
    is_free = models.BooleanField(default=True)  # False = cần Premium (nhãn PRO)
    learner_base = models.PositiveIntegerField(
        default=0
    )  # số học viên nền khi seed; số hiển thị = learner_base + số người đã mở bộ
    vocabulary = models.ManyToManyField(
        Vocabulary, through="VocabularyDeckItem", related_name="decks"
    )

    class Meta:
        ordering = ["collection__order", "order"]

    def __str__(self) -> str:
        return str(self.title_vi)


class VocabularyDeckItem(models.Model):
    """1 thẻ trong bộ — thứ tự học do `order` quyết định."""

    deck = models.ForeignKey(VocabularyDeck, on_delete=models.CASCADE, related_name="items")
    vocabulary = models.ForeignKey(Vocabulary, on_delete=models.CASCADE, related_name="deck_items")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["deck", "vocabulary"], name="uniq_deck_vocab")
        ]
        ordering = ["order"]

    def __str__(self) -> str:
        return f"{self.deck_id} · {self.order}. {self.vocabulary_id}"
