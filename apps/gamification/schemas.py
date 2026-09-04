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
