"""C50 Cửa hàng — lõi nghiệp vụ: giá/khuyến mãi, hiệu ứng vật phẩm, rương may mắn, ví, wishlist.

Mọi thay đổi xu đi qua CoinTransaction; mỗi lần mua có ShopReceipt (idempotent theo
Idempotency-Key) để trả lại đúng kết quả cũ, kể cả phần thưởng ngẫu nhiên.
"""

import random
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone as djtz

from apps.common.exceptions import Conflict
from apps.learning import services as learn
from apps.notifications.models import Notification

from .models import CoinTransaction, ShopItem, ShopReceipt, ShopWishlist, UserCosmetic

# Chỉ bán vật phẩm mà `apply_effects` thực sự cài hiệu ứng, tránh trừ xu mà không có gì xảy ra.
# Xu KHÔNG đổi được Premium — quyền Premium chỉ đến từ apps.billing (webhook/redeem).
SUPPORTED_EFFECTS = {
    "hearts",
    "streak_freeze",
    "xp_boost",
    "streak_repair",
    "mystery_box",
    "cosmetic",
}
XP_BOOST_MULTIPLIER = 2
STREAK_REPAIR_WINDOW = timedelta(hours=48)
PREMIUM_COIN_BONUS_PCT = 50

# Rương may lắc: (trọng số, hiệu ứng). Kỳ vọng ≈ 0.85 giá rương để không lạm phát xu.
MYSTERY_TABLE = [
    (30, {"coins": 50}),
    (20, {"coins": 150}),
    (5, {"coins": 400}),
    (15, {"hearts": 5}),
    (15, {"streak_freeze": 1}),
    (15, {"xp_boost": 30}),
]


# ---------------------------------------------------------------- giá / bán được
def sellable(item: ShopItem) -> bool:
    return bool(SUPPORTED_EFFECTS & set((item.effect or {}).keys()))


def on_sale(item: ShopItem, now=None) -> bool:
    if item.discount_pct <= 0:
        return False
    return item.sale_until is None or item.sale_until > (now or djtz.now())


def price_of(item: ShopItem, now=None) -> int:
    if not on_sale(item, now):
        return item.cost_coins
    return max(0, item.cost_coins * (100 - min(item.discount_pct, 100)) // 100)


# ---------------------------------------------------------------- trạng thái hồ sơ
def xp_boost_active(profile, now=None) -> bool:
    return bool(profile.xp_boost_until and profile.xp_boost_until > (now or djtz.now()))


def streak_repairable(profile, now=None) -> bool:
    now = now or djtz.now()
    return bool(
        profile.streak_lost_value > 0
        and profile.streak_lost_at
        and profile.streak_lost_at + STREAK_REPAIR_WINDOW > now
    )


def premium_active(profile, now=None) -> bool:
    if not profile.is_premium:
        return False
    return profile.premium_until is None or profile.premium_until > (now or djtz.now())


def owned_cosmetic_ids(user) -> set[int]:
    return set(UserCosmetic.objects.filter(user=user).values_list("item_id", flat=True))


def wishlist_ids(user) -> set[int]:
    return set(ShopWishlist.objects.filter(user=user).values_list("item_id", flat=True))


# ---------------------------------------------------------------- mua
@dataclass
class Purchase:
    item: ShopItem
    coins_spent: int
    balance: int
    granted: dict


def _hearts_only(eff: dict) -> bool:
    return set(eff.keys()) & SUPPORTED_EFFECTS == {"hearts"}


def check_purchasable(profile, item: ShopItem, now) -> None:
    """Ném Conflict nếu vật phẩm không có ý nghĩa với người dùng lúc này."""
    eff = item.effect or {}
    if _hearts_only(eff) and profile.hearts >= learn.HEARTS_MAX:
        raise Conflict("Tim đã đầy", code="hearts_full")
    if "streak_repair" in eff and not streak_repairable(profile, now):
        raise Conflict("Không có streak nào cần hồi sinh", code="nothing_to_repair")
    if "cosmetic" in eff and UserCosmetic.objects.filter(user=profile.user, item=item).exists():
        raise Conflict("Bạn đã sở hữu vật phẩm này", code="already_owned")


def roll_mystery_box(rng: random.Random | None = None) -> dict:
    rng = rng or random
    weights = [w for w, _ in MYSTERY_TABLE]
    return dict(rng.choices([e for _, e in MYSTERY_TABLE], weights=weights, k=1)[0])


def apply_effects(profile, effects: dict, *, item: ShopItem, now, ref_id: str) -> dict:
    """Cài hiệu ứng lên hồ sơ (chưa save). Trả về hiệu ứng THỰC nhận (rương → phần thưởng cụ thể).
    Xu thưởng (rương) được cộng và ghi sổ ngay tại đây."""
    granted: dict = {}
    for key, raw in (effects or {}).items():
        n = int(raw or 0)
        if key == "hearts":
            before = profile.hearts
            profile.hearts = min(learn.HEARTS_MAX, profile.hearts + n)
            granted["hearts"] = profile.hearts - before
        elif key == "streak_freeze":
            profile.streak_freezes += n
            granted["streak_freeze"] = n
        elif key == "xp_boost":
            base = profile.xp_boost_until if xp_boost_active(profile, now) else now
            profile.xp_boost_until = base + timedelta(minutes=n)
            granted["xp_boost"] = n
        elif key == "streak_repair":
            if streak_repairable(profile, now):
                profile.streak_current += profile.streak_lost_value
                profile.streak_best = max(profile.streak_best, profile.streak_current)
                granted["streak_repair"] = profile.streak_lost_value
                profile.streak_lost_value = 0
                profile.streak_lost_at = None
        elif key == "mystery_box":
            prize = roll_mystery_box()
            if "coins" in prize:
                profile.coins += prize["coins"]
                CoinTransaction.objects.create(
                    user=profile.user,
                    amount=prize["coins"],
                    reason="mystery_box",
                    ref_type="shop_purchase",
                    ref_id=ref_id,
                    balance_after=profile.coins,
                )
                granted["coins"] = granted.get("coins", 0) + prize["coins"]
            else:
                inner = apply_effects(profile, prize, item=item, now=now, ref_id=ref_id)
                for k, v in inner.items():
                    granted[k] = granted.get(k, 0) + v
            granted["mystery_box"] = granted.get("mystery_box", 0) + 1
        elif key == "cosmetic":
            UserCosmetic.objects.get_or_create(user=profile.user, item=item)
            if not profile.avatar_frame:
                profile.avatar_frame = item.code
            granted["cosmetic"] = 1
    return granted


PROFILE_FIELDS = [
    "coins",
    "hearts",
    "streak_freezes",
    "xp_boost_until",
    "streak_current",
    "streak_best",
    "streak_lost_value",
    "streak_lost_at",
    "avatar_frame",
]


def purchase(profile, item: ShopItem, idempotency_key: str) -> Purchase:
    user = profile.user
    existing = ShopReceipt.objects.filter(user=user, idempotency_key=idempotency_key).first()
    if existing:
        return Purchase(
            item=existing.item,
            coins_spent=existing.coins_spent,
            balance=existing.balance_after,
            granted=existing.granted or {},
        )
    now = djtz.now()
    price = price_of(item, now)
    if profile.coins < price:
        raise Conflict("Không đủ xu", code="insufficient_coins")
    check_purchasable(profile, item, now)

    with transaction.atomic():
        profile.coins -= price
        CoinTransaction.objects.create(
            user=user,
            amount=-price,
            reason="shop_purchase",
            ref_type="shop_purchase",
            ref_id=idempotency_key,
            balance_after=profile.coins,
        )
        granted = apply_effects(
            profile, item.effect or {}, item=item, now=now, ref_id=idempotency_key
        )
        profile.save(update_fields=PROFILE_FIELDS)
        ShopReceipt.objects.create(
            user=user,
            item=item,
            idempotency_key=idempotency_key,
            coins_spent=price,
            balance_after=profile.coins,
            granted=granted,
        )
        # Mua xong thì bỏ khỏi wishlist (đã đạt mục tiêu).
        ShopWishlist.objects.filter(user=user, item=item).delete()
    return Purchase(item=item, coins_spent=price, balance=profile.coins, granted=granted)


# ---------------------------------------------------------------- trang trí
def equip_cosmetic(profile, item: ShopItem | None) -> None:
    if item is None:
        profile.avatar_frame = ""
    else:
        if not UserCosmetic.objects.filter(user=profile.user, item=item).exists():
            raise Conflict("Bạn chưa sở hữu vật phẩm này", code="not_owned")
        profile.avatar_frame = item.code
    profile.save(update_fields=["avatar_frame"])


def frame_colors(code: str) -> list[str]:
    if not code:
        return []
    item = ShopItem.objects.filter(code=code).only("meta").first()
    return list((item.meta or {}).get("colors", [])) if item else []


def frame_colors_map(codes) -> dict[str, list[str]]:
    """Một query cho cả danh sách (bảng xếp hạng); code lạ/rỗng → []."""
    wanted = {c for c in codes if c}
    if not wanted:
        return {}
    return {
        code: list((meta or {}).get("colors", []))
        for code, meta in ShopItem.objects.filter(code__in=wanted).values_list("code", "meta")
    }


# ---------------------------------------------------------------- wishlist
def notify_wishlist(profile) -> int:
    """Gọi sau khi cộng xu: báo 1 lần cho mỗi vật phẩm wishlist mà số dư đã đủ mua."""
    now = djtz.now()
    due = [
        w
        for w in ShopWishlist.objects.filter(
            user=profile.user, notified_at__isnull=True
        ).select_related("item")
        if w.item.is_active and price_of(w.item, now) <= profile.coins
    ]
    for w in due:
        Notification.objects.create(
            user=profile.user,
            kind=Notification.Kind.REWARD,
            title_vi=f"Đủ xu đổi {w.item.title_vi} rồi!",
            body_vi=f"Bạn đang có {profile.coins} xu — vào Cửa hàng để đổi ngay.",
            data={"screen": "shop", "item_id": w.item_id},
        )
        w.notified_at = now
        w.save(update_fields=["notified_at"])
    return len(due)


# ---------------------------------------------------------------- premium
def coin_bonus(profile, coins: int, now=None) -> int:
    """Premium nhận thêm PREMIUM_COIN_BONUS_PCT% xu mọi nguồn (làm tròn xuống)."""
    if coins <= 0 or not premium_active(profile, now):
        return coins
    return coins + coins * PREMIUM_COIN_BONUS_PCT // 100


def grant_coins(profile, coins: int, *, reason: str, ref_type: str = "", ref_id: str = "") -> int:
    """Cộng xu ngoài luồng học (gói xu mua bằng tiền). Trả về số dư mới."""
    with transaction.atomic():
        profile.coins += coins
        profile.save(update_fields=["coins"])
        CoinTransaction.objects.create(
            user=profile.user,
            amount=coins,
            reason=reason,
            ref_type=ref_type,
            ref_id=str(ref_id),
            balance_after=profile.coins,
        )
    notify_wishlist(profile)
    return profile.coins
