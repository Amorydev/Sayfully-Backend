"""G6 game hoá — chunk A: thử thách + huy hiệu. Thưởng đi qua learning.services.record.

Tiến độ thử thách tính từ DailyActivity (không lưu tăng dần). Nhận thưởng idempotent
theo (user, challenge, period_key).
"""

from django.conf import settings
from django.db import transaction
from django.utils import timezone as djtz
from ninja import Router

from apps.accounts.services import ensure_profile
from apps.common.exceptions import Conflict, NotFound
from apps.common.schemas import ErrorOut
from apps.learning import services as learn
from apps.learning.models import DailyActivity

from . import schemas as s
from . import services
from .models import Badge, Challenge, UserBadge, UserChallenge

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
    claims = {
        uc.challenge_id: uc
        for uc in UserChallenge.objects.filter(user=user, period_key=pk)
    }
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
