"""Schema phản hồi cho 21 endpoint nội dung (G2).

Quy ước: `audio_url` là URL đầy đủ (ghép R2_PUBLIC_BASE ở tầng builder);
`ipa` chọn theo `UserProfile.accent`. Endpoint G2 chỉ trả NỘI DUNG — tiến độ
người dùng thuộc G4.
"""

from ninja import Schema


class Page[T](Schema):
    items: list[T]
    count: int
    limit: int
    offset: int


class SyllableOut(Schema):
    text: str
    is_primary: bool
    is_secondary: bool


class ExampleOut(Schema):
    text_en: str
    text_vi: str
    audio_url: str | None


class SentenceOut(Schema):
    text_en: str
    ipa: str | None
    text_vi: str
    audio_url: str | None


# --------------------------------------------------------------- 2.1 Lộ trình
class LevelOut(Schema):
    code: str
    name_vi: str
    tier_label: str
    description_vi: str
    order: int
    word_target: int
    is_free: bool


class UnitOut(Schema):
    id: int
    order: int
    code: str
    title_vi: str
    title_en: str
    description_vi: str
    lesson_count: int
    reward: dict


class LessonBriefOut(Schema):
    id: int
    code: str
    order: int
    title_vi: str
    title_en: str
    est_minutes: int
    xp_reward: int


class UnitDetailOut(Schema):
    id: int
    order: int
    code: str
    title_vi: str
    title_en: str
    description_vi: str
    reward: dict
    lessons: list[LessonBriefOut]


# --------------------------------------------------- 2.1 Chi tiết bài (18 bước)
class UnitRefOut(Schema):
    id: int
    order: int
    title_vi: str
    title_en: str


class IntroStepOut(Schema):
    highlight_vi: str
    preview: list[SentenceOut]


class VocabCardOut(Schema):
    id: int
    headword: str
    pos: str
    level: str
    ipa: str
    syllables: list[SyllableOut]
    meaning_vi: str
    audio_uk_url: str | None
    audio_us_url: str | None
    examples: list[ExampleOut]


class ConjugationRowOut(Schema):
    subject: str
    form: str


class GrammarStepOut(Schema):
    id: int
    title_vi: str
    title_en: str
    formula: str
    note_vi: str
    explanation_vi: str
    common_mistake_vi: str
    conjugation: list[ConjugationRowOut]
    examples: list[SentenceOut]


class DialogueLineOut(Schema):
    order: int
    speaker: str
    is_native: bool
    text_en: str
    ipa: str | None
    text_vi: str
    audio_url: str | None


class DialogueStepOut(Schema):
    id: int
    title_en: str
    title_vi: str
    context_vi: str
    lines: list[DialogueLineOut]


class SpellingStepOut(Schema):
    vocab_id: int | None
    word: str
    meaning_vi: str
    ipa: str | None
    audio_url: str | None
    hint_vi: str


class QuizOptionOut(Schema):
    text: str


class QuizStepOut(Schema):
    prompt_vi: str
    question_word: str
    question_ipa: str | None
    audio_url: str | None
    options: list[QuizOptionOut]
    correct_index: int
    explanation_vi: str
    xp: int


class WritingStepOut(Schema):
    prompt_vi: str
    hint_vi: str
    suggestions: list[str]
    xp: int


class LessonStepOut(Schema):
    order: int
    kind: str
    intro: IntroStepOut | None = None
    vocab: VocabCardOut | None = None
    grammar: GrammarStepOut | None = None
    dialogue: DialogueStepOut | None = None
    spelling: SpellingStepOut | None = None
    writing: WritingStepOut | None = None
    quiz: QuizStepOut | None = None


class LessonDetailOut(Schema):
    code: str
    order: int
    unit: UnitRefOut
    level: str
    title_vi: str
    title_en: str
    description_vi: str
    est_minutes: int
    xp_reward: int
    new_word_count: int
    grammar_count: int
    dialogue_count: int
    steps: list[LessonStepOut]


# --------------------------------------------------------------- 2.2 Từ vựng
class VocabListOut(Schema):
    id: int
    headword: str
    pos: str
    level: str
    meaning_vi: str
    ipa: str
    syllables: list[SyllableOut]
    audio_url: str | None


class CollocationOut(Schema):
    text_en: str
    meaning_vi: str


class VocabDetailOut(Schema):
    id: int
    headword: str
    pos: str
    level: str
    ipa: str
    ipa_uk: str
    ipa_us: str
    syllables: list[SyllableOut]
    meaning_vi: str
    definition_en: str
    audio_uk_url: str | None
    audio_us_url: str | None
    frequency_rank: int | None
    synonyms: list[str]
    word_family: list[str]
    examples: list[ExampleOut]
    collocations: list[CollocationOut]


class TopicOut(Schema):
    id: int
    code: str
    name_vi: str
    name_en: str
    icon: str
    word_count: int


# --------------------------------------------------------------- 2.3 Ngữ pháp
class GrammarListOut(Schema):
    id: int
    level: str
    category: str
    title_vi: str
    title_en: str
    formula: str


class GrammarDetailOut(Schema):
    id: int
    level: str
    category: str
    title_vi: str
    title_en: str
    formula: str
    explanation_vi: str
    common_mistake_vi: str
    conjugation: list[ConjugationRowOut]
    examples: list[SentenceOut]


# --------------------------------------------------------------- 2.4 Đọc & truyện
class ReadingListOut(Schema):
    id: int
    level: str
    order: int
    title_en: str
    title_vi: str
    topic: str | None
    est_minutes: int
    cover_url: str | None
    question_count: int


class ReadingQuestionOut(Schema):
    id: int
    order: int
    question_en: str
    options: list[str]
    answer_index: int
    explanation_vi: str


class ReadingKeywordOut(Schema):
    id: int
    headword: str
    ipa: str
    pos: str
    meaning_vi: str
    synonyms: list[str]


class ReadingDetailOut(Schema):
    id: int
    level: str
    title_en: str
    title_vi: str
    est_minutes: int
    sentences: list[SentenceOut]
    keywords: list[ReadingKeywordOut]
    questions: list[ReadingQuestionOut]


class StoryListOut(Schema):
    id: int
    level: str
    order: int
    title_en: str
    title_vi: str
    genre: str
    synopsis_vi: str
    cover_url: str | None
    scene_count: int


class StorySentenceOut(Schema):
    order: int
    text_en: str
    text_vi: str
    audio_url: str | None


class StorySceneOut(Schema):
    order: int
    illustration_url: str | None
    sentences: list[StorySentenceOut]


class StoryQuestionOut(Schema):
    id: int
    order: int
    question_en: str
    options: list[str]
    answer_index: int
    explanation_vi: str


class StoryDetailOut(Schema):
    id: int
    level: str
    title_en: str
    title_vi: str
    genre: str
    scenes: list[StorySceneOut]
    questions: list[StoryQuestionOut]


# --------------------------------------------------------------- 2.5 Video & shadowing
class VideoListOut(Schema):
    id: int
    youtube_id: str
    level: str
    title_vi: str
    title_en: str
    category: str
    duration_sec: int
    thumbnail_url: str | None
    is_free: bool


class VideoSubtitleOut(Schema):
    order: int
    start_ms: int
    end_ms: int
    text_en: str
    ipa: str
    text_vi: str


class VideoDetailOut(Schema):
    id: int
    youtube_id: str
    level: str
    title_vi: str
    title_en: str
    category: str
    duration_sec: int
    subtitles: list[VideoSubtitleOut]


class ShadowingDeckOut(Schema):
    id: int
    level: str
    order: int
    title_en: str
    title_vi: str
    focus_vi: str
    est_seconds: int
    sentence_count: int
    is_free: bool


class ShadowingSentenceOut(Schema):
    order: int
    text_en: str
    ipa: str
    text_vi: str
    audio_url: str | None


class ShadowingDetailOut(Schema):
    id: int
    level: str
    title_en: str
    title_vi: str
    focus_vi: str
    sentences: list[ShadowingSentenceOut]


# --------------------------------------------------------------- 2.6 Tra cứu
class WordRootOut(Schema):
    id: int
    kind: str
    text: str
    meaning_vi: str
    group_vi: str
    example_count: int


class RootExampleOut(Schema):
    id: int
    headword: str
    ipa: str
    meaning_vi: str


class WordRootDetailOut(Schema):
    id: int
    kind: str
    text: str
    meaning_vi: str
    group_vi: str
    mnemonic_vi: str
    examples: list[RootExampleOut]


class PhrasalVerbOut(Schema):
    id: int
    verb_group: str
    text: str
    ipa: str
    meaning_vi: str
    explanation_vi: str
    level: str
    examples: list[dict]


class IPASoundOut(Schema):
    id: int
    symbol: str
    kind: str
    description_vi: str
    articulation_vi: str
    mouth_image_url: str | None
    sample_words: list[str]
    minimal_pair: dict
    audio_uk_url: str | None
    audio_us_url: str | None


# --------------------------------------------------------------- 2.7 Bundle manifest (G5)
class ManifestLevelOut(Schema):
    code: str
    url: str
    checksum: str
    size: int


class ManifestOut(Schema):
    version: int
    levels: list[ManifestLevelOut]
