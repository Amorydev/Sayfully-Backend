"""Schema G4 — chunk vòng học (home, path, lesson start/complete/progress)."""

from datetime import datetime

from ninja import Schema
from pydantic import Field

from apps.content.schemas import CollocationOut, ExampleOut, SyllableOut


# --------------------------------------------------------------- home (C1, §5.7)
class HomeProfileOut(Schema):
    name: str
    avatar_url: str | None
    cefr_level: str
    level: int
    level_label: str
    xp: int
    coins: int
    hearts: int
    streak_days: int
    is_premium: bool


class DailyGoalOut(Schema):
    words_done: int
    words_target: int
    minutes: int
    xp: int
    xp_target: int
    percent: int


class CurrentLessonOut(Schema):
    code: str
    level: str
    unit_title: str
    title_vi: str
    percent: int
    minutes_left: int


class HomeChallengeOut(Schema):
    id: int
    title: str
    current: int
    target: int
    reward_coins: int


class HomeChallengesOut(Schema):
    done: int
    total: int
    reward_coins: int
    items: list[HomeChallengeOut]


class HomeRankOut(Schema):
    league_tier: str
    rank: int
    xp_week: int


class HomeOut(Schema):
    profile: HomeProfileOut
    unread_notifications: int
    due_review_count: int
    daily_goal: DailyGoalOut
    current_lesson: CurrentLessonOut | None
    challenges: HomeChallengesOut
    rank: HomeRankOut | None


# --------------------------------------------------------------- learn path (C2)
class PathLessonOut(Schema):
    id: int
    code: str
    order: int
    title_vi: str
    est_minutes: int
    xp_reward: int
    status: str  # not_started | in_progress | completed
    stars: int
    is_locked: bool


class PathUnitOut(Schema):
    id: int
    order: int
    code: str
    title_vi: str
    title_en: str
    reward: dict
    lesson_count: int
    done_count: int
    lessons: list[PathLessonOut]


class PathOut(Schema):
    level: str
    units: list[PathUnitOut]


# --------------------------------------------------------------- lesson flow
class LessonCompleteIn(Schema):
    correct_count: int = 0
    total: int = 0
    duration_sec: int = 0


class LessonProgressOut(Schema):
    code: str
    status: str
    step_index: int
    correct_count: int
    total_questions: int
    stars: int
    xp_earned: int
    completed_at: datetime | None


class DayProgressOut(Schema):
    label: str
    active: bool
    is_today: bool


class MilestoneOut(Schema):
    name: str
    target_days: int
    days_left: int


class KeyVocabOut(Schema):
    id: int
    headword: str
    ipa: str
    meaning_vi: str


class LessonResultOut(Schema):
    code: str
    percent: int
    correct_count: int
    total: int
    stars: int
    xp_earned: int
    coins_earned: int
    streak_days: int
    is_streak_record: bool
    leveled_up: bool
    level: int
    week_progress: list[DayProgressOut]
    milestone: MilestoneOut | None
    key_vocab: list[KeyVocabOut]
    srs_cards_created: int
    next_lesson_code: str | None


# --------------------------------------------------------------- SRS review (C48, C7)
class ReviewCardOut(Schema):
    vocab_id: int
    headword: str
    pos: str
    level: str
    ipa: str
    syllables: list[SyllableOut]
    meaning_vi: str
    definition_en: str
    audio_uk_url: str | None
    audio_us_url: str | None
    examples: list[ExampleOut]
    collocations: list[CollocationOut]
    word_family: list[str]
    due_at: datetime
    state: int


class ReviewItemIn(Schema):
    vocab_id: int
    rating: int = Field(ge=1, le=4)  # 1 Quên · 2 Khó · 3 Tốt · 4 Dễ
    duration_ms: int = 0


class ReviewCardResultOut(Schema):
    vocab_id: int
    state: int
    due_at: datetime


class ReviewResultOut(Schema):
    reviewed: int
    xp_earned: int
    streak_days: int
    cards: list[ReviewCardResultOut]


class ReviewStatsOut(Schema):
    studied: int
    mastered: int
    learning: int
    due_today: int
    reviewed_today: int
    retention_percent: int


# --------------------------------------------------------------- vocab status (C6, §5.6)
class VocabSummaryOut(Schema):
    total: int
    studied: int
    mastered: int
    learning: int
    due_today: int
    percent: int


class VocabNotebookOut(Schema):
    total: int
    categories: int


class VocabTopicOut(Schema):
    id: int
    done: int
    total: int


class VocabStatusOut(Schema):
    level: str
    summary: VocabSummaryOut
    week: list[bool]
    notebook: VocabNotebookOut
    topics: list[VocabTopicOut]
    learned_ids: list[int]
    due_ids: list[int]
    fav_ids: list[int]


# --------------------------------------------------------------- notebook (C47)
class NotebookEntryOut(Schema):
    id: int
    vocab_id: int | None
    headword: str
    ipa: str
    meaning_vi: str
    audio_url: str | None
    note: str
    tags: list[str]
    srs_state: int | None
    created_at: datetime


class NotebookCreateIn(Schema):
    vocab_id: int | None = None
    custom_word: str = ""
    custom_meaning: str = ""
    note: str = ""
    tags: list[str] = []
