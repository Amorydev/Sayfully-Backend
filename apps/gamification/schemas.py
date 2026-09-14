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
    period: str = "week"
    tier: str
    time_left_sec: int
    promote_top: int
    safe_top: int
    my_rank: int
    # XP của tôi theo period — để hiện thanh "Bạn" kể cả khi ngoài top 50.
    my_xp: int = 0
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
    category: str  # booster | bundle | cosmetic | special
    cost_coins: int  # giá gốc
    price_coins: int  # giá phải trả (đã trừ khuyến mãi)
    discount_pct: int  # 0 = không giảm
    sale_until: datetime | None = None
    effect: dict
    meta: dict  # cosmetic: {"slot": "avatar_frame", "colors": [...]}
    icon_url: str | None
    owned: bool = False  # cosmetic đã sở hữu
    equipped: bool = False  # cosmetic đang trang bị
    wishlisted: bool = False
    order: int = 0


class PurchaseIn(Schema):
    item_id: int


class PurchaseResultOut(Schema):
    item_code: str
    title_vi: str
    coins_spent: int
    balance: int
    effect: dict  # hiệu ứng THỰC nhận (rương may mắn → phần thưởng cụ thể)


class StreakRepairOut(Schema):
    lost_value: int
    lost_at: datetime
    expires_at: datetime


class WalletOut(Schema):
    coins: int
    hearts: int
    hearts_max: int
    streak_freezes: int
    streak_current: int
    xp_boost_until: datetime | None = None
    xp_boost_active: bool = False
    streak_repair: StreakRepairOut | None = None
    is_premium: bool = False
    premium_until: datetime | None = None
    premium_coin_bonus_pct: int = 0
    avatar_frame: str | None = None
    avatar_frame_colors: list[str] = []
    owned_cosmetic_ids: list[int] = []
    wishlist_item_ids: list[int] = []


class EarnOptionOut(Schema):
    code: str  # checkin | challenge:<code> | game:<code> | premium
    title_vi: str
    subtitle_vi: str = ""
    reward_coins: int  # 0 = tuỳ điểm
    done: bool = False
    current: int = 0
    target: int = 0
    screen: str  # challenges | games | premium


class WishlistOut(Schema):
    item_id: int
    wishlisted: bool
    wishlist_item_ids: list[int]


class EquipIn(Schema):
    item_id: int | None = None  # null = tháo khung


class EquipOut(Schema):
    avatar_frame: str | None
    avatar_frame_colors: list[str]


class CoinTxOut(Schema):
    amount: int
    reason: str  # checkin | challenge | game | lesson | shop_purchase | mystery_box | coin_pack
    ref_type: str
    ref_id: str
    label_vi: str = ""  # shop_purchase: tên vật phẩm
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


# --------------------------------------------------------------- Ghép cặp (C12)
class MatchPairsDifficultyOut(Schema):
    """Một ô độ khó trong popup chọn level."""

    code: str  # easy | medium | hard | expert
    label_vi: str
    pairs: int
    cards: int
    three_star_moves: int
    stars: int  # 0 khi chưa chơi
    best_moves: int  # 0 khi chưa chơi


class MatchPairsStageOut(Schema):
    id: int
    code: str
    title_vi: str
    subtitle_vi: str
    symbol: str
    level: str  # CEFR A1–C2, không phải độ khó
    order: int
    is_unlocked: bool
    is_completed: bool  # có dòng tiến độ, không phải stars > 0
    stars: int  # tổng sao của cả bốn độ khó, tối đa 12
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


# --------------------------------------------------------------- Bậc thầy trọng âm
class StressWordOut(Schema):
    id: int
    headword: str
    meaning_vi: str
    syllables: list[str]  # chính tả: ['beau', 'ti', 'ful']
    ipa_syllables: list[str]  # đã bỏ ˈ ˌ để không lộ đáp án: ['bjuː', 'tɪ', 'fəl']
    primary_stress: int  # chỉ số 0-based trong hai mảng trên
    audio_url: str | None = None


class StressRoundOut(Schema):
    level: str
    words: list[StressWordOut]
