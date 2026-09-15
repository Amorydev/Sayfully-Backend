"""Schema G4 — chunk vòng học (home, path, lesson start/complete/progress)."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from ninja import Schema
from pydantic import Field

from apps.content.schemas import CollocationOut, ExampleOut, SyllableOut


# --------------------------------------------------------------- home (C1, §5.7)
class HomeProfileOut(Schema):
    name: str
    avatar_url: str | None
    avatar_frame_colors: list[str] = []  # khung avatar đang trang bị (C50)
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


class HomeGameOut(Schema):
    id: int
    code: str
    title_vi: str
    description_vi: str
    kind: str
    icon_url: str | None
    min_level: str
    is_locked: bool
    is_featured: bool
    personal_best: int


class HomeLearningToolOut(Schema):
    code: str
    title_vi: str
    description_vi: str
    action: Literal["coming_soon", "notebook", "dictionary", "video", "ipa", "roots", "grammar"]
    is_premium: bool = False
    item_count: int | None = None


class StreakStatusOut(Schema):
    days: int
    freezes: int  # băng dự phòng còn lại
    at_risk: bool  # lỡ hôm qua, chưa hoạt động hôm nay → hoạt động kế tiếp sẽ tiêu băng / mất chuỗi
    frozen_yesterday: bool  # hôm qua đã được băng che (băng đã tiêu)


class HomeOut(Schema):
    checkin_done: bool = False  # đã điểm danh hôm nay → app không hiện dialog điểm danh
    streak: StreakStatusOut | None = None
    profile: HomeProfileOut
    unread_notifications: int
    due_review_count: int
    daily_goal: DailyGoalOut
    current_lesson: CurrentLessonOut | None
    challenges: HomeChallengesOut
    rank: HomeRankOut | None
    games: list[HomeGameOut]
    learning_tools: list[HomeLearningToolOut]


# --------------------------------------------------------------- learn path (C2)
class PathLessonCompletionRewardOut(Schema):
    label_vi: str
    reward_coins: int
    badge_code: str | None
    is_reached: bool


class PathUnitSheetCtaOut(Schema):
    lesson_code: str | None
    label_vi: str
    enabled: bool


class PathUnitSheetOut(Schema):
    progress_percent: int
    xp_total: int
    cta: PathUnitSheetCtaOut


class PathLessonOut(Schema):
    id: int
    code: str
    order: int
    title_vi: str
    display_title_vi: str
    subtitle_vi: str
    est_minutes: int
    xp_reward: int
    status: str  # not_started | in_progress | completed
    stars: int
    is_locked: bool
    state_label_vi: str
    unlock_hint_vi: str | None
    is_primary: bool
    completion_reward: PathLessonCompletionRewardOut | None


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
    sheet: PathUnitSheetOut
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


class WritingCheckIn(Schema):
    draft: str
    step_order: int | None = None


class WritingFeedbackOut(Schema):
    correct: bool
    xp: int
    message_vi: str
    natural_tip_vi: str


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
    frozen: bool = False  # ngày lỡ được Băng streak che


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
    lesson_order: int
    title_vi: str
    unit_order: int
    unit_title_vi: str
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
    mastery_percent: int
    reps: int
    lapses: int
    due_at: datetime | None
    created_at: datetime


class NotebookTagFacetOut(Schema):
    tag: str
    count: int


class NotebookListOut(Schema):
    items: list[NotebookEntryOut]
    count: int
    notebook_total: int
    limit: int
    offset: int
    capacity: int
    is_premium: bool
    tag_facets: list[NotebookTagFacetOut]


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
    streak_before: int  # streak trước khi điểm danh — app hiện "Ngày 12 → Ngày 13"
    streak_days: int
    week: list[DayProgressOut]
    milestone: MilestoneOut | None = None  # cột mốc streak kế tiếp (badge metric=streak)
    freeze_used: bool = False  # lần điểm danh này đã tiêu 1 băng để giữ chuỗi
    freezes_left: int = 0


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
    deck_id: int | None = None  # chủ đề luyện nói (ShadowingDeck) để cộng tiến độ C8a
    listening_topic_id: int | None = None  # chủ đề luyện nghe (ListeningTopic) để cộng tiến độ C9a


class PracticeResultOut(Schema):
    xp_earned: int
    skill: str | None
    skill_level: int | None
    skill_percent: int | None


class SpeakingTopicOut(Schema):
    id: int
    level: str
    title_en: str
    title_vi: str
    phrase_preview: str
    icon: str  # token dự phòng
    icon_url: str | None  # ảnh icon để app render trực tiếp
    background_url: str | None  # ảnh nền card; app dùng placeholder nếu trống/lỗi
    color: str  # màu hex "#RRGGBB", rỗng nếu chưa đặt
    sentence_count: int
    est_minutes: int
    is_premium: bool
    done: int
    total: int
    percent: int


class SpeakingTopicsOut(Schema):
    week_practiced: int  # số câu đã luyện nói trong 7 ngày gần nhất (hero C8a)
    suggested: list[SpeakingTopicOut]  # tab "Gợi ý": chủ đề chưa xong, không khoá
    basic: list[SpeakingTopicOut]  # tab "Cơ bản": toàn bộ chủ đề
    by_lesson: list[SpeakingTopicOut] = []  # tab "Theo bài học": để trống ở v1


class ListeningTopicOut(Schema):
    id: int
    title_vi: str
    icon: str  # token dự phòng
    icon_url: str | None  # ảnh icon để app render trực tiếp
    color: str  # màu hex "#RRGGBB"
    item_count: int  # tổng số câu của chủ đề
    est_minutes: int
    is_premium: bool
    done_choose: int  # số câu đã xong ở mode "Chọn từ"
    done_dictation: int  # số câu đã xong ở mode "Chép chính tả"


class ListeningTopicsOut(Schema):
    week_practiced: int  # số câu đã luyện nghe 7 ngày gần nhất (hero C9a)
    suggested: list[ListeningTopicOut]  # tab "Gợi ý"
    basic: list[ListeningTopicOut]  # tab "Cơ bản"
    by_lesson: list[ListeningTopicOut] = []  # tab "Theo bài học": để trống ở v1


class ListeningItemOut(Schema):
    order: int
    text_en: str  # câu đầy đủ (client tự che từ ở blank_index cho mode choose)
    text_vi: str
    audio_url: str | None
    blank_index: int | None = None  # chỉ có ở mode "choose"
    options: list[str] = []  # chỉ có ở mode "choose"
    answer_index: int | None = None  # chỉ có ở mode "choose" (chấm tại máy)


class ListeningItemsOut(Schema):
    topic_id: int
    mode: str  # "choose" | "dictation"
    total: int
    items: list[ListeningItemOut]


# --------------------------------------------------------------- reading list (C10a)
class ReadingCardProgressOut(Schema):
    status: Literal["not_started", "in_progress", "completed"]
    answered_count: int
    correct_count: int
    progress_percent: int
    score_percent: int
    xp_earned: int


class ReadingListItemOut(Schema):
    id: int
    level: str
    order: int
    title_en: str
    title_vi: str
    topic_id: int | None
    topic: str | None
    est_minutes: int
    cover_url: str | None
    question_count: int
    keyword_preview: list[str]
    is_locked: bool
    progress: ReadingCardProgressOut


class ReadingTopicFacetOut(Schema):
    topic_id: int
    name_vi: str
    count: int


class ReadingListOverviewOut(Schema):
    level: str
    level_label: str
    reading_streak_days: int
    total: int
    completed: int
    in_progress: int
    progress_percent: int


class ReadingListPageOut(Schema):
    items: list[ReadingListItemOut]
    count: int
    limit: int
    offset: int
    overview: ReadingListOverviewOut
    topic_facets: list[ReadingTopicFacetOut]


class ReadingProgressIn(Schema):
    answered_count: int = Field(default=0, ge=0)
    correct_count: int = Field(default=0, ge=0)
    completed: bool = False
    duration_sec: int = Field(default=0, ge=0)


class ReadingProgressResultOut(Schema):
    progress: ReadingCardProgressOut
    xp_awarded: int
    reading_streak_days: int


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


# --------------------------------------------------------------- profile overview (C48)
class ProfileStatsOut(Schema):
    level: int
    cefr_level: str
    cefr_label: str
    xp_total: int
    streak_current: int
    streak_best: int
    coins: int
    hearts: int


class ProfileLeagueOut(Schema):
    tier: int
    tier_label: str
    rank: int
    xp_week: int


class ProfileOverviewOut(Schema):
    id: UUID
    full_name: str
    handle: str
    member_id: str
    avatar_url: str | None
    avatar_frame_colors: list[str] = []
    date_joined: datetime
    is_active: bool
    is_premium: bool
    goal_level: str
    goal_progress_percent: int
    stats: ProfileStatsOut
    league: ProfileLeagueOut | None
    friend_invites: int
    unread_notifications: int
    shop_new: bool


# --------------------------------------------------------------- challenges overview (C6)
class ChallengeLeagueOut(Schema):
    tier: int
    tier_label: str
    division: str
    rank: int
    percentile: int
    time_left_sec: int
    xp_week: int
    xp_week_target: int
    xp_to_next: int
    next_tier_label: str | None
    percent: int


class ChallengeGoalsOut(Schema):
    xp: int
    xp_target: int
    words: int
    words_target: int
    speaking: int
    speaking_target: int
    percent: int


class ChallengeStreakOut(Schema):
    days: int
    week: list[DayProgressOut]


class ChallengeCheckinOut(Schema):
    done_today: bool
    reward_xp: int
    reward_coins: int


class ChallengeTaskOut(Schema):
    id: int
    code: str
    metric: str
    title_vi: str
    description_vi: str
    current: int
    target: int
    reward_xp: int
    reward_coins: int
    completed: bool
    claimed: bool


class ChallengesOverviewOut(Schema):
    level: int
    streak_days: int
    coins: int
    hearts: int
    league: ChallengeLeagueOut
    goals: ChallengeGoalsOut
    streak: ChallengeStreakOut
    checkin: ChallengeCheckinOut
    tasks_done: int
    tasks_total: int
    tasks: list[ChallengeTaskOut]


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


# --------------------------------------------------------------- flashcard decks (C7a → C7)
class FlashcardDeckOut(Schema):
    """1 ô trong lưới thư viện. Đủ để vẽ card, chưa kèm thẻ."""

    id: int
    code: str
    title_vi: str
    cover_title: str
    badge_vi: str
    background_url: str | None
    icon: str
    accent_color: str
    level: str | None
    card_count: int
    learner_count: int
    is_premium: bool
    learned_count: int  # thẻ đã thuộc của người dùng hiện tại (0 nếu chưa học)


class FlashcardDeckCollectionOut(Schema):
    code: str
    title_vi: str
    chip_label_vi: str
    deck_count: int
    decks: list[FlashcardDeckOut]


class FlashcardDecksOut(Schema):
    continuing: FlashcardDeckOut | None  # thẻ "Đang học" ở hero; null nếu chưa mở bộ nào
    collections: list[FlashcardDeckCollectionOut]


class FlashcardDeckCardOut(Schema):
    """1 thẻ trong bộ. Cùng hình dạng `ReviewCardOut` để app dùng chung màn C7;
    `due_at`/`state` rỗng với thẻ người dùng chưa từng ôn."""

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
    due_at: datetime | None = None
    state: int = 0


class FlashcardDeckDetailOut(Schema):
    """Toàn bộ dữ liệu 1 bộ thẻ — gọi khi người dùng bấm vào ô."""

    id: int
    code: str
    title_vi: str
    background_url: str | None
    level: str | None
    total: int
    learned_count: int
    cards: list[FlashcardDeckCardOut]
