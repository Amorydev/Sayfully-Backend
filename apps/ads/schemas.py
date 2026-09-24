"""Schema quảng cáo."""

from datetime import datetime

from ninja import Schema


class AdPlacementOut(Schema):
    slot: str
    title_vi: str
    format: str
    reward_kind: str
    reward_amount: int
    daily_cap: int
    used_today: int
    remaining_today: int
    cooldown_seconds: int
    ad_unit_android: str
    ad_unit_ios: str
    # None = đang được phép xem; ngược lại là mã lý do chặn (xem apps.ads.services).
    blocked_reason: str | None


class AdsConfigOut(Schema):
    enabled: bool
    blocked_reason: str | None
    global_daily_cap: int
    used_today: int
    min_interval_seconds: int
    ticket_ttl_seconds: int
    placements: list[AdPlacementOut]


class AdTicketIn(Schema):
    slot: str
    # Vị trí "nhân đôi xu": mã game vừa chơi, để server đọc đúng ván trong sổ điểm.
    game_code: str = ""


class AdTicketOut(Schema):
    impression_id: str
    slot: str
    format: str
    reward_kind: str
    reward_amount: int
    ad_unit_android: str
    ad_unit_ios: str
    # Gắn vào quảng cáo để SSV ghép được callback với vé này.
    custom_data: str
    user_id: str
    expires_at: datetime


class AdRewardOut(Schema):
    impression_id: str
    status: str
    reward_kind: str
    granted_amount: int
    coins: int
    hearts: int
