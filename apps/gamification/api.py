"""G6 game hoá — chunk A: thử thách + huy hiệu. Thưởng đi qua learning.services.record.

Tiến độ thử thách tính từ DailyActivity (không lưu tăng dần). Nhận thưởng idempotent
theo (user, challenge, period_key).
"""

import random
from datetime import datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone as djtz
from ninja import Header, Query, Router

from apps.accounts.models import User, UserProfile
from apps.accounts.services import ensure_profile
from apps.common.exceptions import AppError, Conflict, NotFound
from apps.common.models import CEFR
from apps.common.schemas import ErrorOut, MessageOut
from apps.content.models import Vocabulary
from apps.content.schemas import Page
from apps.learning import services as learn
from apps.learning.models import DailyActivity, WeeklyStat
from apps.notifications.models import Device, Notification

from . import schemas as s
from . import services, shop
from .models import (
    Badge,
    Challenge,
    CoinTransaction,
    Game,
    GameScore,
    GameStageProgress,
    LeagueMembership,
    MatchPairsProgress,
    MatchPairsStage,
    ShopItem,
    ShopReceipt,
    ShopWishlist,
    UserBadge,
    UserChallenge,
)

router = Router()
CHECKIN_COINS = 10  # khớp learning.api._CHECKIN_COINS


def _media(path: str | None) -> str | None:
    return f"{settings.R2_PUBLIC_BASE.rstrip('/')}/{path}" if path else None


def _dailies(user, scope, today):
    if scope == Challenge.Scope.WEEKLY:
        lo, hi = services.week_range(today)
        return list(DailyActivity.objects.filter(user=user, date__gte=lo, date__lte=hi))
    d = DailyActivity.objects.filter(user=user, date=today).first()
    return [d] if d else []


def _challenge_out(ch, current, uc) -> s.ChallengeOut:
    return s.ChallengeOut(
        id=ch.id,
        code=ch.code,
        scope=ch.scope,
        metric=ch.metric,
        title_vi=ch.title_vi,
        description_vi=ch.description_vi,
        target=ch.target,
        current=min(current, ch.target),
        reward_xp=ch.reward_xp,
        reward_coins=ch.reward_coins,
        completed=current >= ch.target,
        claimed=bool(uc and uc.claimed_at),
    )


def _list_challenges(request, scope):
    user = request.auth
    profile = ensure_profile(user)
    today = learn.local_today(profile)
    dailies = _dailies(user, scope, today)
    pk = services.period_key(scope, today)
    claims = {uc.challenge_id: uc for uc in UserChallenge.objects.filter(user=user, period_key=pk)}
    return [
        _challenge_out(ch, services.challenge_progress(ch, dailies), claims.get(ch.id))
        for ch in Challenge.objects.filter(scope=scope, is_active=True).order_by("tier", "code")
    ]


@router.get(
    "/challenges/today",
    response={200: list[s.ChallengeOut], 401: ErrorOut},
    summary="Thử thách hôm nay",
    description="Nhiệm vụ hằng ngày kèm tiến độ + trạng thái đã nhận thưởng.",
)
def challenges_today(request):
    return _list_challenges(request, Challenge.Scope.DAILY)


@router.get(
    "/challenges/weekly",
    response={200: list[s.ChallengeOut], 401: ErrorOut},
    summary="Thử thách tuần",
    description="Nhiệm vụ theo tuần kèm tiến độ.",
)
def challenges_weekly(request):
    return _list_challenges(request, Challenge.Scope.WEEKLY)


@router.post(
    "/challenges/{id}/claim",
    response={200: s.ClaimResultOut, 401: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Nhận thưởng thử thách",
    description="Chỉ nhận khi đã hoàn thành; nhận lại → `already_claimed`.",
)
def claim_challenge(request, id: int):
    user = request.auth
    profile = ensure_profile(user)
    ch = Challenge.objects.filter(id=id, is_active=True).first()
    if ch is None:
        raise NotFound("Không tìm thấy thử thách")
    today = learn.local_today(profile)
    dailies = _dailies(user, ch.scope, today)
    pk = services.period_key(ch.scope, today)
    current = services.challenge_progress(ch, dailies)
    if current < ch.target:
        raise Conflict("Thử thách chưa hoàn thành", code="challenge_incomplete")

    uc, _ = UserChallenge.objects.get_or_create(user=user, challenge=ch, period_key=pk)
    if uc.claimed_at:
        raise Conflict("Đã nhận thưởng thử thách này", code="already_claimed")

    now = djtz.now()
    with transaction.atomic():
        reward = learn.record(
            profile,
            xp=ch.reward_xp,
            coins=ch.reward_coins,
            coin_reason="challenge",
            ref_type="challenge",
            ref_id=ch.code,
        )
        uc.progress = current
        uc.completed_at = uc.completed_at or now
        uc.claimed_at = now
        uc.save()
    return s.ClaimResultOut(xp_earned=reward.xp_earned, coins_earned=reward.coins_earned)


@router.get(
    "/badges",
    response={200: list[s.BadgeOut], 401: ErrorOut},
    summary="Huy hiệu",
    description="Danh sách huy hiệu + trạng thái mở khoá (tự mở khoá khi đủ điều kiện).",
)
def badges(request):
    user = request.auth
    profile = ensure_profile(user)
    services.check_badges(user, profile)
    earned = dict(UserBadge.objects.filter(user=user).values_list("badge_id", "unlocked_at"))
    return [
        s.BadgeOut(
            code=b.code,
            title_vi=b.title_vi,
            description_vi=b.description_vi,
            icon_url=_media(b.icon_path),
            unlocked=b.id in earned,
            unlocked_at=earned.get(b.id),
        )
        for b in Badge.objects.order_by("order")
    ]


# =============================================================== leaderboard (C16)
def _week_left(now) -> int:
    days_ahead = 7 - now.weekday()
    next_monday = (now + timedelta(days=days_ahead)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int((next_monday - now).total_seconds())


def _entry(rank, user, profile, xp_week, me_id) -> s.LeaderboardEntryOut:
    return s.LeaderboardEntryOut(
        rank=rank,
        name=user.full_name,
        avatar_url=_media(user.avatar_path),
        xp_week=xp_week,
        streak_days=profile.streak_current if profile else 0,
        movement=0,
        is_me=user.id == me_id,
    )


def _league_ranking(user):
    m = services.ensure_league_membership(user)
    group = m.group
    members = list(
        LeagueMembership.objects.filter(group=group).select_related("user", "user__profile")
    )
    xp_map = dict(
        WeeklyStat.objects.filter(
            iso_year=group.iso_year,
            iso_week=group.iso_week,
            user_id__in=[mm.user_id for mm in members],
        ).values_list("user_id", "xp")
    )
    ranked = sorted(members, key=lambda mm: -xp_map.get(mm.user_id, 0))
    my_rank = next((i + 1 for i, mm in enumerate(ranked) if mm.user_id == user.id), 0)
    my_xp = xp_map.get(user.id, 0)
    xp_to_promote = 0
    if my_rank > 5 and len(ranked) >= 5:
        xp_to_promote = max(0, xp_map.get(ranked[4].user_id, 0) - my_xp + 1)
    return group, ranked, xp_map, my_rank, my_xp, xp_to_promote


@router.get(
    "/leaderboard",
    response={200: s.LeaderboardOut, 401: ErrorOut},
    summary="Bảng xếp hạng",
    description="`scope=league` (liên đoàn ~30 người) hoặc `global`; `period=week` (mặc định) hoặc `all` (mọi thời đại, chỉ với scope=global).",
)
def leaderboard(request, scope: str = "league", period: str = "week"):
    user = request.auth
    profile = ensure_profile(user)
    now = djtz.now()
    if scope == "global" and period == "all":
        rows = (
            UserProfile.objects.filter(xp_total__gt=0)
            .select_related("user")
            .order_by("-xp_total", "user_id")[:50]
        )
        entries, my_rank = [], 0
        for i, prof in enumerate(rows):
            entries.append(_entry(i + 1, prof.user, prof, prof.xp_total, user.id))
            if prof.user_id == user.id:
                my_rank = i + 1
        return s.LeaderboardOut(
            scope="global",
            period="all",
            tier="",
            time_left_sec=0,
            promote_top=0,
            safe_top=0,
            my_rank=my_rank,
            my_xp=profile.xp_total,
            xp_to_promote=0,
            entries=entries,
        )
    if scope == "global":
        y, w = services.current_week()
        rows = (
            WeeklyStat.objects.filter(iso_year=y, iso_week=w)
            .select_related("user", "user__profile")
            .order_by("-xp")[:50]
        )
        entries, my_rank = [], 0
        for i, ws in enumerate(rows):
            prof = getattr(ws.user, "profile", None)
            entries.append(_entry(i + 1, ws.user, prof, ws.xp, user.id))
            if ws.user_id == user.id:
                my_rank = i + 1
        my_xp = (
            WeeklyStat.objects.filter(iso_year=y, iso_week=w, user=user)
            .values_list("xp", flat=True)
            .first()
            or 0
        )
        return s.LeaderboardOut(
            scope="global",
            tier="",
            time_left_sec=_week_left(now),
            promote_top=0,
            safe_top=0,
            my_rank=my_rank,
            my_xp=my_xp,
            xp_to_promote=0,
            entries=entries,
        )

    group, ranked, xp_map, my_rank, my_xp, xp_to_promote = _league_ranking(user)
    entries = [
        _entry(
            i + 1, mm.user, getattr(mm.user, "profile", None), xp_map.get(mm.user_id, 0), user.id
        )
        for i, mm in enumerate(ranked)
    ]
    return s.LeaderboardOut(
        scope="league",
        tier=group.get_tier_display(),
        time_left_sec=_week_left(now),
        promote_top=5,
        safe_top=20,
        my_rank=my_rank,
        my_xp=my_xp,
        xp_to_promote=xp_to_promote,
        entries=entries,
    )


@router.get(
    "/leaderboard/me",
    response={200: s.MyRankOut, 401: ErrorOut},
    summary="Hạng của tôi",
    description="Bậc liên đoàn + hạng + XP tuần + XP cần để thăng.",
)
def leaderboard_me(request):
    user = request.auth
    ensure_profile(user)
    group, _, _, my_rank, my_xp, xp_to_promote = _league_ranking(user)
    return s.MyRankOut(
        tier=group.get_tier_display(), rank=my_rank, xp_week=my_xp, xp_to_promote=xp_to_promote
    )


# =============================================================== shop / coins (C50)
# Nghiệp vụ nằm ở gamification.shop; ở đây chỉ dựng response.
def _item_out(it, now, owned, wishlist, equipped_code) -> s.ShopItemOut:
    return s.ShopItemOut(
        id=it.id,
        code=it.code,
        title_vi=it.title_vi,
        description_vi=it.description_vi,
        category=it.category,
        cost_coins=it.cost_coins,
        price_coins=shop.price_of(it, now),
        discount_pct=it.discount_pct if shop.on_sale(it, now) else 0,
        sale_until=it.sale_until if shop.on_sale(it, now) else None,
        effect=it.effect or {},
        meta=it.meta or {},
        icon_url=_media(it.icon_path),
        owned=it.id in owned,
        equipped=bool(equipped_code) and it.code == equipped_code,
        wishlisted=it.id in wishlist,
        order=it.order,
    )


def _wallet_out(user, profile) -> s.WalletOut:
    now = djtz.now()
    learn.regen_hearts(profile)
    repair = None
    if shop.streak_repairable(profile, now):
        repair = s.StreakRepairOut(
            lost_value=profile.streak_lost_value,
            lost_at=profile.streak_lost_at,
            expires_at=profile.streak_lost_at + shop.STREAK_REPAIR_WINDOW,
        )
    premium = shop.premium_active(profile, now)
    return s.WalletOut(
        coins=profile.coins,
        hearts=profile.hearts,
        hearts_max=learn.HEARTS_MAX,
        streak_freezes=profile.streak_freezes,
        streak_current=profile.streak_current,
        xp_boost_until=profile.xp_boost_until if shop.xp_boost_active(profile, now) else None,
        xp_boost_active=shop.xp_boost_active(profile, now),
        streak_repair=repair,
        is_premium=premium,
        premium_until=profile.premium_until if premium else None,
        premium_coin_bonus_pct=shop.PREMIUM_COIN_BONUS_PCT,
        avatar_frame=profile.avatar_frame or None,
        avatar_frame_colors=shop.frame_colors(profile.avatar_frame),
        owned_cosmetic_ids=sorted(shop.owned_cosmetic_ids(user)),
        wishlist_item_ids=sorted(shop.wishlist_ids(user)),
    )


@router.get(
    "/shop/wallet",
    response={200: s.WalletOut, 401: ErrorOut},
    summary="Ví cửa hàng",
    description="Xu, tim, băng, boost XP đang chạy, streak có thể hồi sinh, khung avatar, wishlist.",
)
def shop_wallet(request):
    user = request.auth
    return _wallet_out(user, ensure_profile(user))


@router.get(
    "/shop/items",
    response={200: list[s.ShopItemOut], 401: ErrorOut},
    summary="Vật phẩm cửa hàng",
    description=(
        "Danh sách vật phẩm mua bằng xu (chỉ vật phẩm có hiệu ứng đã cài). "
        "`price_coins` là giá sau khuyến mãi; `category` để chia tab."
    ),
)
def shop_items(request):
    user = request.auth
    profile = ensure_profile(user)
    now = djtz.now()
    owned = shop.owned_cosmetic_ids(user)
    wishlist = shop.wishlist_ids(user)
    return [
        _item_out(it, now, owned, wishlist, profile.avatar_frame)
        for it in ShopItem.objects.filter(is_active=True).order_by("order", "code")
        if shop.sellable(it)
    ]


@router.post(
    "/shop/purchase",
    response={200: s.PurchaseResultOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Mua vật phẩm (idempotent)",
    description=(
        "Cần header `Idempotency-Key`. Thiếu xu → `insufficient_coins`; "
        "mua bơm tim khi tim đã đầy → `hearts_full`; hồi sinh streak khi không mất → "
        "`nothing_to_repair`; trang trí đã có → `already_owned`. "
        "`effect` trả về là hiệu ứng thực nhận (rương may mắn → phần thưởng cụ thể)."
    ),
)
def shop_purchase(
    request,
    payload: s.PurchaseIn,
    idempotency_key: str = Header(None, alias="Idempotency-Key"),
):
    user = request.auth
    profile = ensure_profile(user)
    if not idempotency_key:
        raise AppError(
            "Thiếu header Idempotency-Key", code="idempotency_key_missing", status_code=400
        )
    item = ShopItem.objects.filter(id=payload.item_id, is_active=True).first()
    if item is None or not shop.sellable(item):
        raise NotFound("Không tìm thấy vật phẩm")
    learn.regen_hearts(profile)
    result = shop.purchase(profile, item, idempotency_key)
    return s.PurchaseResultOut(
        item_code=result.item.code,
        title_vi=result.item.title_vi,
        coins_spent=result.coins_spent,
        balance=result.balance,
        effect=result.granted,
    )


@router.get(
    "/shop/earn",
    response={200: list[s.EarnOptionOut], 401: ErrorOut},
    summary="Cách kiếm xu",
    description="Gợi ý cụ thể để kiếm xu hôm nay: điểm danh, nhiệm vụ chưa nhận, mini-game, Premium.",
)
def shop_earn(request):
    user = request.auth
    profile = ensure_profile(user)
    today = learn.local_today(profile)
    tz = ZoneInfo(profile.timezone)
    start_today = datetime.combine(today, dtime.min, tz)
    out = [
        s.EarnOptionOut(
            code="checkin",
            title_vi="Điểm danh hôm nay",
            subtitle_vi="Mỗi ngày một lần, giữ streak",
            reward_coins=CHECKIN_COINS,
            done=CoinTransaction.objects.filter(
                user=user, reason="checkin", created_at__gte=start_today
            ).exists(),
            screen="challenges",
        )
    ]
    dailies = _dailies(user, Challenge.Scope.DAILY, today)
    pk = services.period_key(Challenge.Scope.DAILY, today)
    claims = {uc.challenge_id: uc for uc in UserChallenge.objects.filter(user=user, period_key=pk)}
    for ch in Challenge.objects.filter(scope=Challenge.Scope.DAILY, is_active=True).order_by(
        "tier", "code"
    ):
        cur = services.challenge_progress(ch, dailies)
        uc = claims.get(ch.id)
        out.append(
            s.EarnOptionOut(
                code=f"challenge:{ch.code}",
                title_vi=ch.title_vi,
                subtitle_vi=ch.description_vi,
                reward_coins=ch.reward_coins,
                done=bool(uc and uc.claimed_at),
                current=min(cur, ch.target),
                target=ch.target,
                screen="challenges",
            )
        )
    for g in Game.objects.filter(is_active=True).order_by("order"):
        out.append(
            s.EarnOptionOut(
                code=f"game:{g.code}",
                title_vi=f"Chơi {g.title_vi}",
                subtitle_vi="Tối đa 15 xu mỗi ván theo điểm",
                reward_coins=15,
                screen="games",
            )
        )
    if not shop.premium_active(profile):
        out.append(
            s.EarnOptionOut(
                code="premium",
                title_vi=f"Premium: +{shop.PREMIUM_COIN_BONUS_PCT}% xu mọi nguồn",
                subtitle_vi="Áp dụng cho điểm danh, nhiệm vụ, mini-game",
                reward_coins=0,
                screen="premium",
            )
        )
    return out


@router.post(
    "/shop/wishlist/{item_id}",
    response={200: s.WishlistOut, 401: ErrorOut, 404: ErrorOut},
    summary="Thêm vào wishlist",
    description="Nhận thông báo khi đủ xu mua vật phẩm này (báo 1 lần).",
)
def shop_wishlist_add(request, item_id: int):
    user = request.auth
    ensure_profile(user)
    item = ShopItem.objects.filter(id=item_id, is_active=True).first()
    if item is None:
        raise NotFound("Không tìm thấy vật phẩm")
    ShopWishlist.objects.get_or_create(user=user, item=item)
    return s.WishlistOut(
        item_id=item_id, wishlisted=True, wishlist_item_ids=sorted(shop.wishlist_ids(user))
    )


@router.delete(
    "/shop/wishlist/{item_id}",
    response={200: s.WishlistOut, 401: ErrorOut},
    summary="Bỏ khỏi wishlist",
)
def shop_wishlist_remove(request, item_id: int):
    user = request.auth
    ensure_profile(user)
    ShopWishlist.objects.filter(user=user, item_id=item_id).delete()
    return s.WishlistOut(
        item_id=item_id, wishlisted=False, wishlist_item_ids=sorted(shop.wishlist_ids(user))
    )


@router.post(
    "/shop/cosmetics/equip",
    response={200: s.EquipOut, 401: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Trang bị / tháo khung avatar",
    description="`item_id` null → tháo khung. Chưa sở hữu → `not_owned`.",
)
def shop_equip(request, payload: s.EquipIn):
    user = request.auth
    profile = ensure_profile(user)
    item = None
    if payload.item_id is not None:
        item = ShopItem.objects.filter(
            id=payload.item_id, category=ShopItem.Category.COSMETIC
        ).first()
        if item is None:
            raise NotFound("Không tìm thấy vật phẩm")
    shop.equip_cosmetic(profile, item)
    return s.EquipOut(
        avatar_frame=profile.avatar_frame or None,
        avatar_frame_colors=shop.frame_colors(profile.avatar_frame),
    )


@router.get(
    "/coins/transactions",
    response={200: Page[s.CoinTxOut], 401: ErrorOut},
    summary="Sổ cái xu",
    description="Lịch sử giao dịch xu (mới nhất trước).",
)
def coin_transactions(request, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    user = request.auth
    ensure_profile(user)
    qs = CoinTransaction.objects.filter(user=user).order_by("-created_at")
    count = qs.count()
    items = list(qs[offset : offset + limit])
    # Tên vật phẩm cho giao dịch mua (ref_id = Idempotency-Key của biên lai).
    keys = [t.ref_id for t in items if t.ref_type == "shop_purchase" and t.ref_id]
    titles = {
        r.idempotency_key: r.item.title_vi
        for r in ShopReceipt.objects.filter(user=user, idempotency_key__in=keys).select_related("item")
    }
    return Page(
        items=[
            s.CoinTxOut(
                amount=t.amount,
                reason=t.reason,
                ref_type=t.ref_type,
                ref_id=t.ref_id,
                label_vi=titles.get(t.ref_id, "") if t.ref_type == "shop_purchase" else "",
                balance_after=t.balance_after,
                created_at=t.created_at,
            )
            for t in items
        ],
        count=count,
        limit=limit,
        offset=offset,
    )


# =============================================================== mini-games (C12, C31, C32)
@router.get(
    "/games",
    response={200: list[s.GameOut], 401: ErrorOut},
    summary="Danh sách trò chơi",
    description="Trò chơi + kỷ lục cá nhân.",
)
def games(request):

    user = request.auth
    ensure_profile(user)
    best = dict(
        GameScore.objects.filter(user=user)
        .values_list("game")
        .annotate(m=Max("score"))
        .values_list("game", "m")
    )
    return [
        s.GameOut(
            id=g.id,
            code=g.code,
            title_vi=g.title_vi,
            description_vi=g.description_vi,
            kind=g.kind,
            icon_url=_media(g.icon_path),
            min_level=g.min_level,
            is_featured=g.is_featured,
            personal_best=best.get(g.id, 0),
        )
        for g in Game.objects.filter(is_active=True).order_by("order")
    ]


@router.post(
    "/games/{code}/scores",
    response={200: s.GameScoreResultOut, 401: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    summary="Nộp điểm ván chơi",
    description="Ghi điểm, cộng xu/XP theo điểm, trả kỷ lục + percentile.",
)
def submit_score(request, code: str, payload: s.GameScoreIn):

    user = request.auth
    profile = ensure_profile(user)
    game = Game.objects.filter(code=code, is_active=True).first()
    if game is None:
        raise NotFound("Không tìm thấy trò chơi")

    prev_best = GameScore.objects.filter(user=user, game=game).aggregate(m=Max("score"))["m"] or 0
    coins = min(15, payload.score // 80)
    xp = min(10, payload.score // 100)
    with transaction.atomic():
        learn.record(
            profile, xp=xp, coins=coins, coin_reason="game", ref_type="game", ref_id=game.code
        )
        GameScore.objects.create(
            user=user,
            game=game,
            level=payload.level or profile.cefr_level,
            score=payload.score,
            accuracy=payload.accuracy,
            coins_earned=coins,
        )
        if payload.level and payload.stage_index is not None:
            _record_stage(
                user, game, payload.level, payload.stage_index, payload.score, payload.accuracy
            )
    total = GameScore.objects.filter(game=game).count()
    below = GameScore.objects.filter(game=game, score__lt=payload.score).count()
    return s.GameScoreResultOut(
        score=payload.score,
        coins_earned=coins,
        xp_earned=xp,
        is_record=payload.score > prev_best,
        personal_best=max(prev_best, payload.score),
        percentile=round(below / total * 100) if total else 0,
    )


def _record_stage(user, game, level: str, stage_index: int, score: int, accuracy: float) -> None:
    """Chỉ nâng, không hạ: chơi lại một chặng với điểm thấp hơn không xoá kỷ lục cũ."""
    row, created = GameStageProgress.objects.get_or_create(
        user=user,
        game=game,
        level=level.upper(),
        stage_index=stage_index,
        defaults={"best_score": score, "best_accuracy": accuracy, "play_count": 1},
    )
    if not created:
        row.best_score = max(row.best_score, score)
        row.best_accuracy = max(row.best_accuracy, accuracy)
        row.play_count += 1
        row.save(update_fields=["best_score", "best_accuracy", "play_count", "updated_at"])


@router.get(
    "/games/{code}/stages",
    response={200: s.GameStageMapOut, 401: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    summary="Path map các chặng của một cấp",
    description="Chia từ vựng của cấp thành các chặng liên tiếp (25 từ/chặng) theo đúng thứ tự "
    "của `GET /content/vocabulary?level=`, nên `offset` của chặng dùng thẳng để tải từ. "
    "Chặng 0 luôn mở; chặng n mở khi chặng n-1 đã hoàn thành.",
)
def game_stages(request, code: str, level: str = Query(...)):
    from apps.content.models import Vocabulary

    user = request.auth
    game = Game.objects.filter(code=code, is_active=True).first()
    if game is None:
        raise NotFound("Không tìm thấy trò chơi")
    level = level.upper()
    if level not in CEFR.values:
        raise AppError("Cấp độ không hợp lệ", code="invalid_level", status_code=422)

    size = GameStageProgress.STAGE_SIZE
    total = Vocabulary.objects.filter(level_id=level).count()
    stage_count = (total + size - 1) // size
    done = {
        row.stage_index: row
        for row in GameStageProgress.objects.filter(user=user, game=game, level=level)
    }
    stages: list[s.GameStageOut] = []
    for index in range(stage_count):
        row = done.get(index)
        stages.append(
            s.GameStageOut(
                index=index,
                offset=index * size,
                word_count=min(size, total - index * size),
                is_unlocked=index == 0 or (index - 1) in done,
                is_completed=row is not None,
                best_score=row.best_score if row else 0,
                best_accuracy=row.best_accuracy if row else 0.0,
            )
        )
    return s.GameStageMapOut(
        level=level,
        stage_size=size,
        total_words=total,
        completed_stages=len(done),
        stages=stages,
    )


@router.get(
    "/games/leaderboard",
    response={200: s.LeaderboardOut, 401: ErrorOut, 404: ErrorOut},
    summary="Bảng xếp hạng trò chơi",
    description="Điểm cao nhất mỗi người cho một trò (`code`); `period=week|all`.",
)
def game_leaderboard(request, code: str, period: str = "week"):

    user = request.auth
    ensure_profile(user)
    game = Game.objects.filter(code=code).first()
    if game is None:
        raise NotFound("Không tìm thấy trò chơi")
    now = djtz.now()
    qs = GameScore.objects.filter(game=game)
    if period == "week":
        qs = qs.filter(played_at__gte=now - timedelta(days=now.weekday()))
    # Khoá phụ `user_id` để hoà điểm không đảo thứ hạng giữa hai lần gọi: điểm Ghép cặp
    # chỉ có 12 giá trị nên hoà là chuyện thường.
    rows = list(
        qs.values_list("user_id").annotate(best=Max("score")).order_by("-best", "user_id")[:50]
    )

    users = {
        u.id: u for u in User.objects.filter(id__in=[r[0] for r in rows]).select_related("profile")
    }
    entries, my_rank = [], 0
    for i, (uid, best) in enumerate(rows):
        u = users.get(uid)
        if u is None:
            continue
        entries.append(_entry(i + 1, u, getattr(u, "profile", None), best, user.id))
        if uid == user.id:
            my_rank = i + 1
    return s.LeaderboardOut(
        scope="game",
        tier="",
        time_left_sec=_week_left(now),
        promote_top=0,
        safe_top=0,
        my_rank=my_rank,
        xp_to_promote=0,
        entries=entries,
    )


# =============================================================== Ghép cặp (C12)
def _playable_stages() -> list[MatchPairsStage]:
    """Đúng một truy vấn, không kéo từ nào về: A6 tự lấy `stage.pairs` của một chặng."""
    return list(MatchPairsStage.objects.playable())


def _unlocked_ids(stages: list[MatchPairsStage], played: set[int]) -> set[int]:
    """
    Chặng đầu luôn mở; chặng kế mở khi chặng liền trước đã có dòng tiến độ. Chặng
    đã có dòng tiến độ thì luôn mở — biên tập viên chèn chặng mới lên trước không
    được khoá lại chặng người chơi đã qua.
    """
    unlocked: set[int] = set()
    previous_completed = True
    for stage in stages:
        completed = stage.id in played
        if previous_completed or completed:
            unlocked.add(stage.id)
        previous_completed = completed
    return unlocked


def _difficulty_rows(
    progress_by_difficulty: dict[str, MatchPairsProgress],
) -> list[s.MatchPairsDifficultyOut]:
    rows = []
    for choice in MatchPairsProgress.Difficulty:
        row = progress_by_difficulty.get(choice.value)
        pairs = MatchPairsProgress.pairs_for(choice.value)
        rows.append(
            s.MatchPairsDifficultyOut(
                code=choice.value,
                label_vi=choice.label,
                pairs=pairs,
                cards=pairs * 2,
                three_star_moves=MatchPairsProgress.thresholds_for(choice.value)[0],
                stars=row.stars if row else 0,
                best_moves=row.best_moves if row else 0,
            )
        )
    return rows


@router.get(
    "/match-pairs/stages",
    response={200: s.MatchPairsStageMapOut, 401: ErrorOut},
    summary="Bản đồ chặng Ghép cặp",
    description="Chặng biên tập tay kèm sao của từng độ khó. Chặng 0 luôn mở; "
    "chặng n mở khi chặng n-1 đã chơi ít nhất một độ khó.",
)
def match_pairs_stages(request):
    user = request.auth
    ensure_profile(user)
    stages = _playable_stages()
    progress: dict[int, dict[str, MatchPairsProgress]] = {}
    for row in MatchPairsProgress.objects.filter(user=user, stage__in=stages):
        progress.setdefault(row.stage_id, {})[row.difficulty] = row
    unlocked = _unlocked_ids(stages, set(progress))

    out: list[s.MatchPairsStageOut] = []
    total_stars = 0
    completed_stages = 0
    for stage in stages:
        rows = progress.get(stage.id, {})
        stars = sum(row.stars for row in rows.values())
        # Tín hiệu hoàn thành là *có dòng tiến độ*, không phải số sao: một dòng 0 sao
        # tạo tay qua trang quản trị vẫn tính là đã chơi, và vẫn mở chặng kế.
        completed = bool(rows)
        total_stars += stars
        completed_stages += 1 if completed else 0
        out.append(
            s.MatchPairsStageOut(
                id=stage.id,
                code=stage.code,
                title_vi=stage.title_vi,
                subtitle_vi=stage.subtitle_vi,
                symbol=stage.symbol,
                level=stage.level,
                order=stage.order,
                is_unlocked=stage.id in unlocked,
                is_completed=completed,
                stars=stars,
                difficulties=_difficulty_rows(rows),
            )
        )

    return s.MatchPairsStageMapOut(
        total_stars=total_stars,
        max_stars=len(stages) * len(MatchPairsProgress.Difficulty) * 3,
        completed_stages=completed_stages,
        stages=out,
    )


def _open_stage(user, stage_id: int) -> tuple[MatchPairsStage, list[MatchPairsStage], set[int]]:
    """
    Chặng đang mở, kèm danh sách chặng đã dựng và tập id chặng người chơi đã có
    dòng tiến độ. Trả cả ba để endpoint nộp kết quả không dựng lại danh sách chỉ
    để tìm chặng kế, và không hỏi `.exists()` lần nữa để biết "đã chơi chưa".
    """
    stages = _playable_stages()
    stage = next((item for item in stages if item.id == stage_id), None)
    if stage is None:
        raise NotFound("Không tìm thấy chặng")
    played = set(
        MatchPairsProgress.objects.filter(user=user, stage__in=stages).values_list(
            "stage_id", flat=True
        )
    )
    if stage.id not in _unlocked_ids(stages, played):
        raise AppError("Chặng chưa mở khoá", code="stage_locked", status_code=403)
    return stage, stages, played


def _check_difficulty(difficulty: str) -> str:
    if difficulty not in MatchPairsProgress.Difficulty.values:
        raise AppError("Độ khó không hợp lệ", code="invalid_difficulty", status_code=422)
    return difficulty


@router.get(
    "/match-pairs/stages/{stage_id}/round",
    response={
        200: s.MatchPairsRoundOut,
        401: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        422: ErrorOut,
    },
    summary="Bốc một ván Ghép cặp",
    description="Rút ngẫu nhiên đủ số cặp cho độ khó. Rút lại mỗi lần gọi nên chơi lại "
    "cùng chặng sẽ gặp từ khác.",
)
def match_pairs_round(request, stage_id: int, difficulty: str = Query(...)):
    user = request.auth
    difficulty = _check_difficulty(difficulty)
    stage, _, _ = _open_stage(user, stage_id)
    wanted = MatchPairsProgress.pairs_for(difficulty)
    chosen = random.sample(list(stage.pairs.all()), wanted)
    three_star_moves, two_star_moves = MatchPairsProgress.thresholds_for(difficulty)
    return s.MatchPairsRoundOut(
        stage_id=stage.id,
        difficulty=difficulty,
        pairs=[s.MatchPairsWordOut(english=p.english, vietnamese=p.vietnamese) for p in chosen],
        three_star_moves=three_star_moves,
        two_star_moves=two_star_moves,
    )


@router.post(
    "/match-pairs/stages/{stage_id}/result",
    response={
        200: s.MatchPairsResultOut,
        401: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        422: ErrorOut,
    },
    summary="Nộp kết quả một ván Ghép cặp",
    description="Máy chủ tự chấm sao từ số lượt lật, cộng xu/XP và mở chặng kế. "
    "Kỷ lục chỉ nâng: chơi lại tệ hơn không xoá sao cũ.",
)
def match_pairs_result(request, stage_id: int, payload: s.MatchPairsResultIn):
    user = request.auth
    profile = ensure_profile(user)
    difficulty = _check_difficulty(payload.difficulty)
    stage, stages, played = _open_stage(user, stage_id)
    # Chặng đã có dòng tiến độ trước ván này chưa — quyết định có báo "vừa mở khoá" hay không.
    was_played = stage.id in played
    pairs = MatchPairsProgress.pairs_for(difficulty)
    # Ít hơn `pairs` lượt là không thể: mỗi cặp cần tối thiểu một lượt lật. Quá trần
    # cột `best_moves` thì cũng từ chối, không để DB nổ.
    if not pairs <= payload.moves <= MatchPairsProgress.MAX_MOVES:
        raise AppError("Số lượt lật không hợp lệ", code="invalid_moves", status_code=422)

    stars = MatchPairsProgress.stars_for(difficulty, payload.moves)
    score = pairs * 100 * stars
    coins = min(15, score // 80)
    xp = min(10, score // 100)
    game = Game.objects.filter(code="match_pairs", is_active=True).first()

    with transaction.atomic():
        learn.record(
            profile, xp=xp, coins=coins, coin_reason="game", ref_type="game", ref_id="match_pairs"
        )
        row, created = MatchPairsProgress.objects.get_or_create(
            user=user,
            stage=stage,
            difficulty=difficulty,
            defaults={"stars": stars, "best_moves": payload.moves, "play_count": 1},
        )
        if not created:
            row.stars = max(row.stars, stars)
            row.best_moves = min(row.best_moves, payload.moves) if row.best_moves else payload.moves
            row.play_count += 1
            row.save(update_fields=["stars", "best_moves", "play_count", "updated_at"])
        if game is not None:
            GameScore.objects.create(
                user=user,
                game=game,
                level=stage.level,
                score=score,
                accuracy=pairs / payload.moves,
                coins_earned=coins,
            )

    # Chỉ báo chặng kế ở lần đầu hoàn thành chặng này; chơi lại không "mở khoá" lần nữa,
    # nếu không client sẽ ăn mừng mở khoá mỗi lần chơi lại.
    unlocked = None
    if not was_played:
        for index, item in enumerate(stages):
            if item.id == stage.id and index + 1 < len(stages):
                nxt = stages[index + 1]
                # Chặng kế đã có dòng tiến độ (biên tập viên chèn chặng này lên trước) thì
                # nó vốn đã mở — không báo mở khoá lần nữa.
                if nxt.id not in played:
                    unlocked = nxt.id
                break

    return s.MatchPairsResultOut(
        stars=stars,
        best_stars=row.stars,
        best_moves=row.best_moves,
        coins_earned=coins,
        xp_earned=xp,
        unlocked_stage_id=unlocked,
    )


# =============================================================== notifications + devices (C46)
@router.get(
    "/notifications",
    response={200: Page[s.NotificationOut], 401: ErrorOut},
    summary="Trung tâm thông báo",
    description="Thông báo (mới nhất trước), kèm cờ đã đọc + deep-link ở `data`.",
)
def notifications(request, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    user = request.auth
    ensure_profile(user)
    qs = Notification.objects.filter(user=user).order_by("-created_at")
    count = qs.count()
    items = qs[offset : offset + limit]
    return Page(
        items=[
            s.NotificationOut(
                id=n.id,
                kind=n.kind,
                title_vi=n.title_vi,
                body_vi=n.body_vi,
                data=n.data or {},
                is_read=n.read_at is not None,
                created_at=n.created_at,
            )
            for n in items
        ],
        count=count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/notifications/unread-count",
    response={200: s.UnreadCountOut, 401: ErrorOut},
    summary="Số thông báo chưa đọc",
    description="Cho chấm đỏ trên chuông.",
)
def unread_count(request):
    user = request.auth
    ensure_profile(user)
    return s.UnreadCountOut(
        count=Notification.objects.filter(user=user, read_at__isnull=True).count()
    )


@router.post(
    "/notifications/read",
    response={200: MessageOut, 401: ErrorOut},
    summary="Đánh dấu đã đọc",
    description="`all=true` đọc hết, hoặc `ids=[...]` đọc theo danh sách.",
)
def mark_read(request, payload: s.NotificationReadIn):
    user = request.auth
    ensure_profile(user)
    qs = Notification.objects.filter(user=user, read_at__isnull=True)
    if not payload.all:
        qs = qs.filter(id__in=payload.ids or [])
    qs.update(read_at=djtz.now())
    return MessageOut(message="Đã đánh dấu đã đọc")


@router.post(
    "/devices",
    response={200: s.DeviceOut, 401: ErrorOut},
    summary="Đăng ký thiết bị nhận push",
    description="Upsert theo `fcm_token`. Bắt buộc để nhắc streak.",
)
def register_device(request, payload: s.DeviceIn):
    user = request.auth
    ensure_profile(user)
    device, _ = Device.objects.update_or_create(
        fcm_token=payload.fcm_token,
        defaults={
            "user": user,
            "platform": payload.platform,
            "app_version": payload.app_version,
            "is_active": True,
        },
    )
    return s.DeviceOut(id=device.id, platform=device.platform, is_active=device.is_active)


# ----------------------------------------------------------------- Bậc thầy trọng âm
STRESS_ROUND_MIN, STRESS_ROUND_DEFAULT, STRESS_ROUND_MAX = 5, 30, 50


def _stress_words(level: str) -> list[Vocabulary]:
    """Từ chơi được: đã gen_ipa, ≥ 2 âm tiết, chính tả và IPA tách cùng số đoạn, trọng âm nằm trong mảng."""
    qs = (
        Vocabulary.objects.filter(
            level_id=level, primary_stress__isnull=False, syllables__len__gte=2
        )
        .exclude(ipa_us="")
        .only(
            "id",
            "headword",
            "meaning_vi",
            "syllables",
            "ipa_syllables",
            "primary_stress",
            "audio_us_path",
        )
    )
    return [
        v
        for v in qs
        if len(v.syllables) == len(v.ipa_syllables) and 0 <= v.primary_stress < len(v.syllables)
    ]


def _bare_ipa(syllable: str) -> str:
    """Dấu nhấn trong IPA chính là đáp án — bỏ đi trước khi gửi xuống máy."""
    return syllable.replace("ˈ", "").replace("ˌ", "")


@router.get(
    "/stress-master/round",
    response={200: s.StressRoundOut, 401: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    summary="Bốc từ cho một ván Bậc thầy trọng âm",
    description="Trả ngẫu nhiên các từ đa âm tiết của một cấp CEFR kèm âm tiết, IPA (đã bỏ dấu nhấn) "
    "và chỉ số âm tiết mang trọng âm chính. Điểm nộp qua POST /games/stress_master/scores.",
)
def stress_master_round(
    request,
    level: str = Query(...),
    count: int = Query(STRESS_ROUND_DEFAULT, ge=STRESS_ROUND_MIN, le=STRESS_ROUND_MAX),
):
    ensure_profile(request.auth)
    level = level.upper()
    if level not in CEFR.values:
        raise AppError("Cấp không hợp lệ", code="invalid_level", status_code=422)
    words = _stress_words(level)
    if len(words) < STRESS_ROUND_MIN:
        raise NotFound("Cấp này chưa đủ từ có trọng âm")
    chosen = random.sample(words, min(count, len(words)))
    return s.StressRoundOut(
        level=level,
        words=[
            s.StressWordOut(
                id=v.id,
                headword=v.headword,
                meaning_vi=v.meaning_vi,
                syllables=v.syllables,
                ipa_syllables=[_bare_ipa(p) for p in v.ipa_syllables],
                primary_stress=v.primary_stress,
                audio_url=_media(v.audio_us_path),
            )
            for v in chosen
        ],
    )
