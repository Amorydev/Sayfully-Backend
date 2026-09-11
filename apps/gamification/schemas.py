"""Schema G6 — game hoá."""

from datetime import datetime

from ninja import Schema


class ChallengeOut(Schema):
    id: int
    code: str
    scope: str
    metric: str
    title_vi: str
    description_vi: str
    target: int
    current: int
    reward_xp: int
    reward_coins: int
    completed: bool
    claimed: bool


class ClaimResultOut(Schema):
    xp_earned: int
    coins_earned: int


class BadgeOut(Schema):
    code: str
    title_vi: str
    description_vi: str
    icon_url: str | None
    unlocked: bool
    unlocked_at: datetime | None


# --------------------------------------------------------------- leaderboard (C16)
class LeaderboardEntryOut(Schema):
    rank: int
    name: str
    avatar_url: str | None
    xp_week: int
    streak_days: int
    movement: int
    is_me: bool


class LeaderboardOut(Schema):
    scope: str
    tier: str
    time_left_sec: int
    promote_top: int
    safe_top: int
    my_rank: int
    xp_to_promote: int
    entries: list[LeaderboardEntryOut]


class MyRankOut(Schema):
    tier: str
    rank: int
    xp_week: int
    xp_to_promote: int


# --------------------------------------------------------------- shop / coins (C50)
class ShopItemOut(Schema):
    id: int
    code: str
    title_vi: str
    description_vi: str
    cost_coins: int
    effect: dict
    icon_url: str | None


class PurchaseIn(Schema):
    item_id: int


class PurchaseResultOut(Schema):
    item_code: str
    coins_spent: int
    balance: int
    effect: dict


class CoinTxOut(Schema):
    amount: int
    reason: str
    ref_type: str
    ref_id: str
    balance_after: int
    created_at: datetime


# --------------------------------------------------------------- mini-games (C12, C31, C32)
class GameOut(Schema):
    id: int
    code: str
    title_vi: str
    description_vi: str
    kind: str
    icon_url: str | None
    min_level: str
    is_featured: bool
    personal_best: int


class GameScoreIn(Schema):
    score: int
    duration_sec: int = 0
    # Ván chơi theo path map: ghi kèm tiến độ chặng. Bỏ trống = ván tự do.
    level: str | None = None
    stage_index: int | None = None
    accuracy: float = 0


class GameStageOut(Schema):
    index: int
    offset: int
    word_count: int
    is_unlocked: bool
    is_completed: bool
    best_score: int
    best_accuracy: float


class GameStageMapOut(Schema):
    level: str
    stage_size: int
    total_words: int
    completed_stages: int
    stages: list[GameStageOut]


class GameScoreResultOut(Schema):
    score: int
    coins_earned: int
    xp_earned: int
    is_record: bool
    personal_best: int
    percentile: int


# --------------------------------------------------------------- notifications + devices (C46)
class NotificationOut(Schema):
    id: int
    kind: str
    title_vi: str
    body_vi: str
    data: dict
    is_read: bool
    created_at: datetime


class UnreadCountOut(Schema):
    count: int


class NotificationReadIn(Schema):
    ids: list[int] | None = None
    all: bool = False


class DeviceIn(Schema):
    fcm_token: str
    platform: str
    app_version: str = ""


class DeviceOut(Schema):
    id: int
    platform: str
    is_active: bool


# --------------------------------------------------------------- Ghép cặp
class MatchPairsDifficultyOut(Schema):
    """Một ô độ khó trong popup chọn level."""

    code: str          # easy | medium | hard | expert
    label_vi: str
    pairs: int
    cards: int
    three_star_moves: int
    stars: int         # 0 khi chưa chơi
    best_moves: int    # 0 khi chưa chơi


class MatchPairsStageOut(Schema):
    id: int
    code: str
    title_vi: str
    subtitle_vi: str
    symbol: str
    level: str
    order: int
    is_unlocked: bool
    is_completed: bool
    stars: int         # tổng sao của cả bốn độ khó, tối đa 12
    difficulties: list[MatchPairsDifficultyOut]


class MatchPairsStageMapOut(Schema):
    total_stars: int
    max_stars: int
    completed_stages: int
    stages: list[MatchPairsStageOut]


class MatchPairsWordOut(Schema):
    english: str
    vietnamese: str


class MatchPairsRoundOut(Schema):
    stage_id: int
    difficulty: str
    pairs: list[MatchPairsWordOut]
    three_star_moves: int
    two_star_moves: int


class MatchPairsResultIn(Schema):
    difficulty: str
    moves: int
    duration_sec: int = 0


class MatchPairsResultOut(Schema):
    stars: int
    best_stars: int
    best_moves: int
    coins_earned: int
    xp_earned: int
    unlocked_stage_id: int | None = None
