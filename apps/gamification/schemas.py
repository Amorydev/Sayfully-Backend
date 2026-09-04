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
