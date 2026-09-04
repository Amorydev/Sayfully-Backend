"""G6 game hoá — chunk A: thử thách + huy hiệu. Thưởng đi qua learning.services.record.

Tiến độ thử thách tính từ DailyActivity (không lưu tăng dần). Nhận thưởng idempotent
theo (user, challenge, period_key).
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone as djtz
from ninja import Header, Query, Router

from apps.accounts.models import User
from apps.accounts.services import ensure_profile
from apps.common.exceptions import AppError, Conflict, NotFound
from apps.common.schemas import ErrorOut
from apps.content.schemas import Page
from apps.learning import services as learn
from apps.learning.models import DailyActivity, WeeklyStat

from . import schemas as s
from . import services
from .models import (
    Badge,
    Challenge,
    CoinTransaction,
    Game,
    GameScore,
    LeagueMembership,
    ShopItem,
    UserBadge,
    UserChallenge,
)

router = Router()


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
        learn.record(
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
    return s.ClaimResultOut(xp_earned=ch.reward_xp, coins_earned=ch.reward_coins)


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
    description="`scope=league` (liên đoàn ~30 người) hoặc `global` (toàn cầu tuần này).",
)
def leaderboard(request, scope: str = "league", period: str = "week"):
    user = request.auth
    ensure_profile(user)
    now = djtz.now()
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
        return s.LeaderboardOut(
            scope="global",
            tier="",
            time_left_sec=_week_left(now),
            promote_top=0,
            safe_top=0,
            my_rank=my_rank,
            xp_to_promote=0,
            entries=entries,
        )

    group, ranked, xp_map, my_rank, _, xp_to_promote = _league_ranking(user)
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
@router.get(
    "/shop/items",
    response={200: list[s.ShopItemOut], 401: ErrorOut},
    summary="Vật phẩm cửa hàng",
    description="Danh sách vật phẩm mua bằng xu.",
)
def shop_items(request):
    ensure_profile(request.auth)
    return [
        s.ShopItemOut(
            id=it.id,
            code=it.code,
            title_vi=it.title_vi,
            description_vi=it.description_vi,
            cost_coins=it.cost_coins,
            effect=it.effect or {},
            icon_url=_media(it.icon_path),
        )
        for it in ShopItem.objects.filter(is_active=True).order_by("code")
    ]


@router.post(
    "/shop/purchase",
    response={200: s.PurchaseResultOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Mua vật phẩm (idempotent)",
    description="Cần header `Idempotency-Key`. Thiếu xu → `insufficient_coins`.",
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
    if item is None:
        raise NotFound("Không tìm thấy vật phẩm")

    existing = CoinTransaction.objects.filter(
        user=user, ref_type="shop_purchase", ref_id=idempotency_key
    ).first()
    if existing:
        return s.PurchaseResultOut(
            item_code=item.code,
            coins_spent=-existing.amount,
            balance=existing.balance_after,
            effect=item.effect or {},
        )
    if profile.coins < item.cost_coins:
        raise Conflict("Không đủ xu", code="insufficient_coins")

    eff = item.effect or {}
    with transaction.atomic():
        profile.coins -= item.cost_coins
        if "hearts" in eff:
            profile.hearts = min(learn.HEARTS_MAX, profile.hearts + int(eff["hearts"]))
        if "streak_freeze" in eff:
            profile.streak_freezes += int(eff["streak_freeze"])
        profile.save(update_fields=["coins", "hearts", "streak_freezes"])
        CoinTransaction.objects.create(
            user=user,
            amount=-item.cost_coins,
            reason="shop_purchase",
            ref_type="shop_purchase",
            ref_id=idempotency_key,
            balance_after=profile.coins,
        )
    return s.PurchaseResultOut(
        item_code=item.code, coins_spent=item.cost_coins, balance=profile.coins, effect=eff
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
    items = qs[offset : offset + limit]
    return Page(
        items=[
            s.CoinTxOut(
                amount=t.amount,
                reason=t.reason,
                ref_type=t.ref_type,
                ref_id=t.ref_id,
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
            level=profile.cefr_level,
            score=payload.score,
            coins_earned=coins,
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
    rows = list(qs.values_list("user_id").annotate(best=Max("score")).order_by("-best")[:50])

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
