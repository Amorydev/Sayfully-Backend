"""Schema Gia sư AI (C17 trò chuyện · C44 hub/đóng vai · C33 tổng kết)."""

from typing import Literal

from ninja import Field, Schema


class QuotaOut(Schema):
    used: int
    limit: int
    left: int
    is_premium: bool
    resets_at: str  # ISO date local kế tiếp


class TopicOut(Schema):
    code: str
    emoji: str
    title_vi: str


class ScenarioOut(Schema):
    id: int
    level: str
    scene: str
    topic: str
    title_vi: str
    description_vi: str
    goal_count: int
    duration_min: int
    is_premium: bool
    locked: bool
    completed: bool
    best_score: int | None


class ScenarioDetailOut(ScenarioOut):
    ai_role_vi: str
    user_role_vi: str
    goals: list[str]
    goal_hints: list[str]
    tip_vi: str
    xp_reward: int
    coin_reward: int


class ContinueOut(Schema):
    conversation_id: int
    kind: str
    title_vi: str
    goals_done: int
    goals_total: int
    turns: int
    minutes_ago: int


class HistoryItemOut(Schema):
    conversation_id: int
    kind: str
    title_vi: str
    turns: int
    mistake_count: int
    score: int | None
    ended_at: str


class AiHubOut(Schema):
    quota: QuotaOut
    continue_session: ContinueOut | None
    scenarios: list[ScenarioOut]
    history: list[HistoryItemOut]
    topics: list[TopicOut]
    notebook_words: list[str]


class CorrectionOut(Schema):
    original: str
    corrected: str
    note_vi: str
    grammar_id: int | None


class VocabOut(Schema):
    word: str
    vocab_id: int | None
    saved: bool


class SuggestedReplyOut(Schema):
    en: str
    vi: str


class MessageOut(Schema):
    id: int
    role: str  # user | assistant
    text: str
    reply_vi: str | None = None
    correction: CorrectionOut | None = None
    vocab: list[VocabOut] = []
    praise_vi: str | None = None
    suggested_replies: list[SuggestedReplyOut] = []
    created_at: str


class TurnOut(Schema):
    message: MessageOut
    goals_state: list[bool]
    goals_completed: list[int]
    suggested_end: bool
    turns: int
    quota: QuotaOut


class ConversationOut(Schema):
    id: int
    kind: str
    title_vi: str
    topic: str
    scenario: ScenarioDetailOut | None
    goals_state: list[bool]
    turns: int
    ended: bool
    messages: list[MessageOut]
    suggested_end: bool
    quota: QuotaOut


class StartConversationIn(Schema):
    kind: Literal["tutor", "roleplay"] = "tutor"
    scenario_id: int | None = None
    topic: str = "random"
    use_notebook: bool = True


class SendTurnIn(Schema):
    text: str = Field(..., min_length=1, max_length=600)
    client_msg_id: str = Field("", max_length=64)
    via: Literal["voice", "keyboard"] = "voice"


class GoalResultOut(Schema):
    label_vi: str
    done: bool
    evidence: str | None
    hint_en: str


class SummaryOut(Schema):
    conversation_id: int
    kind: str
    title_vi: str
    score: int | None
    verdict_vi: str
    summary_vi: str
    turns: int
    minutes: int
    mistake_count: int
    top_mistakes: list[CorrectionOut]
    vocab: list[VocabOut]
    goals: list[GoalResultOut]
    goals_all_done: bool
    xp: int
    bonus_xp: int
    coins: int
    rewarded: bool
    min_turns_for_reward: int
    streak_days: int
    next_scenario_id: int | None


class HistoryPageOut(Schema):
    items: list[HistoryItemOut]
    count: int
    limit: int
    offset: int
