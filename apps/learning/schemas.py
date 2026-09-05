"""Schema G4 — chunk vòng học (home, path, lesson start/complete/progress)."""

from datetime import date, datetime
from typing import Literal

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
    subtitle: str
    description_vi: str
    status: str  # not_started | in_progress | completed | locked
    is_locked: bool
    reward: dict
    lesson_count: int
    done_count: int
    lessons: list[PathLessonOut]


class PathMilestoneOut(Schema):
    name: str
    title_vi: str
    requirement_lessons: int
    current_lessons: int
    reward_xp: int
    reward_coins: int
    is_reached: bool


class PathProgressOut(Schema):
    lessons_done: int
    lessons_total: int
    xp_earned: int
    xp_target: int


class PathOut(Schema):
    level: str
    level_name: str
    tier_label: str
    progress: PathProgressOut
    units: list[PathUnitOut]
    milestones: list[PathMilestoneOut]


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


# --------------------------------------------------------------- activity / checkin (C13, C14)
class CheckinOut(Schema):
    already: bool
    xp_earned: int
    coins_earned: int
    streak_days: int
    week: list[DayProgressOut]


class DailyActivityOut(Schema):
    date: date
    xp: int
    lessons_completed: int
    words_reviewed: int
    speaking_count: int
    minutes: int


# --------------------------------------------------------------- practice + skills (C4, C8-C10)
class PracticeIn(Schema):
    kind: Literal["speaking", "listening", "dictation", "shadowing", "reading", "story", "video"]
    score: int = Field(ge=0, le=100)
    duration_sec: int = 0
    ref_id: str = ""


class PracticeResultOut(Schema):
    xp_earned: int
    skill: str | None
    skill_level: int | None
    skill_percent: int | None


class SkillProgressOut(Schema):
    kind: str
    percent: int
    level: int


class PracticeSuggestionOut(Schema):
    kind: str
    title: str
    est_minutes: int
    xp: int


class SkillsOverviewOut(Schema):
    skills: list[SkillProgressOut]
    suggestion: PracticeSuggestionOut | None


# --------------------------------------------------------------- practice hub (C19)
class PracticeFeaturedOut(Schema):
    title_vi: str
    topic: str
    description_vi: str
    is_premium: bool
    thumbnail_url: str | None


class PracticeGameOut(Schema):
    id: int
    code: str
    title_vi: str
    description_vi: str
    kind: str
    icon_url: str | None
    is_featured: bool


class PracticeSkillCountsOut(Schema):
    speaking: int   # số bài luyện nói sẵn sàng ("12 bài sẵn sàng")
    listening: int  # số bài luyện nghe
    reading: int    # số bài đọc ("5 bài mới")
    writing: int    # số bài luyện viết/ngữ pháp


class PracticeCountsOut(Schema):
    vocab_due: int        # "24 từ cần ôn"
    notebook_total: int   # "348 từ đã lưu"
    ipa_sounds: int       # "44 âm IPA"
    videos: int
    skills: PracticeSkillCountsOut


class PracticeHubOut(Schema):
    streak_days: int
    coins: int
    hearts: int
    is_premium: bool
    featured: PracticeFeaturedOut | None
    skills: list[SkillProgressOut]
    counts: PracticeCountsOut
    games: list[PracticeGameOut]


# --------------------------------------------------------------- me preferences (C49, C21, C22)
_CEFR = Literal["A1", "A2", "B1", "B2", "C1", "C2"]


class MePreferencesIn(Schema):
    goal_level: _CEFR | None = None
    cefr_level: _CEFR | None = None
    learning_goal: Literal["daily", "ielts", "toeic", "travel", "media", "kids"] | None = None
    accent: Literal["US", "UK"] | None = None
    show_ipa: bool | None = None
    daily_goal_xp: int | None = None
    daily_goal_words: int | None = None
    timezone: str | None = None
    full_name: str | None = None
    ui_language: str | None = None
    reminder_enabled: bool | None = None
    reminder_time: str | None = None  # "HH:MM"
    streak_reminder: bool | None = None
    event_notifications: bool | None = None
    onboarding_completed: bool | None = None


class PreferencesOut(Schema):
    full_name: str
    goal_level: str
    cefr_level: str
    learning_goal: str
    accent: str
    show_ipa: bool
    daily_goal_xp: int
    daily_goal_words: int
    timezone: str
    ui_language: str
    reminder_enabled: bool
    reminder_time: str
    streak_reminder: bool
    event_notifications: bool
    is_premium: bool
    onboarding_completed: bool
    onboarding_completed_at: datetime | None = None


class AvatarOut(Schema):
    avatar_url: str


# --------------------------------------------------------------- placement (C23)
class PlacementQuestionOut(Schema):
    id: int
    order: int
    skill: str
    prompt_en: str
    options: list[str]
    audio_url: str | None


class PlacementAnswerIn(Schema):
    question_id: int
    answer: int


class PlacementSkillScoreOut(Schema):
    skill: str
    correct: int
    total: int
    label: str


class PlacementResultOut(Schema):
    suggested_level: str
    start_unit_code: str | None
    skill_scores: list[PlacementSkillScoreOut]
    days_saved: int
