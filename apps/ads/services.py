"""Luật quảng cáo: ai được xem, xem bao nhiêu, thưởng bao nhiêu.

Mọi quyết định nằm ở đây — API chỉ gọi và dịch ra HTTP. Client có bản sao của luật này
để vẽ nút, nhưng **server là nguồn sự thật**: trần ngày, khoảng cách giữa hai lượt và
số xu tối đa mỗi ngày đều được kiểm lại ở bước xin vé và bước cộng thưởng.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone as djtz

from apps.accounts.models import UserProfile
from apps.gamification import shop
from apps.learning import services as learn
from apps.learning.models import DailyActivity

from .models import AdImpression, AdPlacement

# Mã lý do chặn — hợp đồng với client, client phân nhánh trên các mã này.
ADS_DISABLED = "ads_disabled"
PREMIUM = "premium"
GRACE_PERIOD = "grace_period"
SLOT_DISABLED = "slot_disabled"
DAILY_CAP = "daily_cap"
GLOBAL_CAP = "global_cap"
COOLDOWN = "cooldown"
COIN_CAP = "coin_cap"
HEARTS_FULL = "hearts_full"
NO_REWARD_CONTEXT = "no_reward_context"
ALREADY_REWARDED = "already_rewarded"

BLOCK_MESSAGES = {
    ADS_DISABLED: "Quảng cáo đang tắt",
    PREMIUM: "Tài khoản Premium không có quảng cáo",
    GRACE_PERIOD: "Tài khoản mới chưa hiển thị quảng cáo",
    SLOT_DISABLED: "Vị trí quảng cáo đang tắt",
    DAILY_CAP: "Hết lượt xem hôm nay",
    GLOBAL_CAP: "Hết lượt xem hôm nay",
    COOLDOWN: "Vui lòng chờ trước khi xem tiếp",
    COIN_CAP: "Đã đạt trần xu từ quảng cáo hôm nay",
    HEARTS_FULL: "Tim đã đầy",
    NO_REWARD_CONTEXT: "Không tìm thấy ván chơi để nhân đôi xu",
    ALREADY_REWARDED: "Ván này đã được nhân đôi rồi",
}


@dataclass(frozen=True)
class AdState:
    """Ảnh chụp hạn mức quảng cáo của một người dùng tại một thời điểm."""

    local_date: object
    total_today: int
    per_slot: dict[str, int]
    coins_today: int
    last_at: datetime | None
    in_grace: bool
    is_premium: bool

    @property
    def coins_left(self) -> int:
        return max(0, settings.ADS_DAILY_COIN_CAP - self.coins_today)

    @property
    def global_left(self) -> int:
        return max(0, settings.ADS_GLOBAL_DAILY_CAP - self.total_today)


def placements() -> list[AdPlacement]:
    return list(AdPlacement.objects.all())


def in_grace(profile: UserProfile, now: datetime) -> bool:
    """Tài khoản mới: chưa đủ ngày *hoặc* chưa đủ số bài học thì không thấy quảng cáo."""
    if settings.ADS_GRACE_DAYS and profile.user.date_joined > now - timedelta(
        days=settings.ADS_GRACE_DAYS
    ):
        return True
    if settings.ADS_GRACE_LESSONS:
        done = (
            DailyActivity.objects.filter(user=profile.user).aggregate(n=Sum("lessons_completed"))[
                "n"
            ]
            or 0
        )
        return done < settings.ADS_GRACE_LESSONS
    return False


def user_state(profile: UserProfile, now: datetime | None = None) -> AdState:
    now = now or djtz.now()
    today = learn.local_today(profile)
    rows = AdImpression.objects.filter(user=profile.user, local_date=today).exclude(
        status=AdImpression.Status.REJECTED
    )
    per_slot: dict[str, int] = {}
    total = 0
    coins = 0
    for slot, kind, granted in rows.values_list("slot", "reward_kind", "granted_amount"):
        per_slot[slot] = per_slot.get(slot, 0) + 1
        total += 1
        if kind == AdPlacement.Reward.COINS:
            coins += granted
    last_at = (
        AdImpression.objects.filter(user=profile.user)
        .exclude(status=AdImpression.Status.REJECTED)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    return AdState(
        local_date=today,
        total_today=total,
        per_slot=per_slot,
        coins_today=coins,
        last_at=last_at,
        in_grace=in_grace(profile, now),
        is_premium=shop.premium_active(profile, now),
    )


def global_block(state: AdState) -> str | None:
    """Lý do chặn không phụ thuộc vị trí — dùng cho cả màn cấu hình."""
    if not settings.ADS_ENABLED:
        return ADS_DISABLED
    if state.is_premium:
        return PREMIUM
    if state.in_grace:
        return GRACE_PERIOD
    return None


def blocked_reason(
    profile: UserProfile,
    placement: AdPlacement,
    state: AdState,
    now: datetime | None = None,
) -> str | None:
    """None = được xem. Ngược lại trả mã lý do (xem hằng số phía trên)."""
    now = now or djtz.now()
    reason = global_block(state)
    if reason:
        return reason
    if not placement.is_enabled:
        return SLOT_DISABLED
    # Native không đi qua vé nên không có "lượt" để đếm: áp trần/cooldown của quảng cáo có thưởng
    # vào đây sẽ làm thẻ native biến mất 45 giây sau mỗi lần xem thưởng, rồi mất hẳn khi hết trần.
    if placement.format == AdPlacement.Format.NATIVE:
        return None
    if state.per_slot.get(placement.slot, 0) >= placement.daily_cap:
        return DAILY_CAP
    if state.global_left <= 0:
        return GLOBAL_CAP
    if state.last_at is not None:
        waited = (now - state.last_at).total_seconds()
        if waited < max(settings.ADS_MIN_INTERVAL_SEC, placement.cooldown_seconds):
            return COOLDOWN
    if placement.reward_kind == AdPlacement.Reward.COINS and state.coins_left <= 0:
        return COIN_CAP
    if placement.reward_kind == AdPlacement.Reward.HEARTS:
        learn.regen_hearts(profile)
        if profile.hearts >= learn.HEARTS_MAX:
            return HEARTS_FULL
    return None


def remaining_today(placement: AdPlacement, state: AdState) -> int:
    used = state.per_slot.get(placement.slot, 0)
    return max(0, min(placement.daily_cap - used, state.global_left))


def resolve_reward(
    profile: UserProfile,
    placement: AdPlacement,
    game_code: str = "",
    now: datetime | None = None,
) -> tuple[int, str]:
    """Mức thưởng thật của một vé, kèm nguồn đã dùng để tính.

    Với `last_game_coins`, thưởng bằng đúng số xu ván vừa chơi (trần là `reward_amount`) — server
    tự đọc từ sổ điểm thay vì tin con số client gửi lên, nếu không "nhân đôi" sẽ thành muốn bao
    nhiêu cũng được. Nguồn trả kèm để một ván chỉ được nhân đôi đúng một lần.
    """
    from apps.gamification.models import CoinTransaction, GameScore  # noqa: PLC0415 — import vòng

    now = now or djtz.now()
    since = now - timedelta(seconds=settings.ADS_REWARD_CONTEXT_SEC)

    if placement.reward_source == AdPlacement.RewardSource.LAST_GAME_COINS:
        rows = GameScore.objects.filter(user=profile.user, played_at__gte=since)
        if game_code:
            rows = rows.filter(game__code=game_code)
        row = rows.order_by("-played_at").values("id", "coins_earned").first()
        if row is None:
            return 0, ""
        return min(row["coins_earned"], placement.reward_amount), f"game_score:{row['id']}"

    if placement.reward_source == AdPlacement.RewardSource.LAST_COIN_REWARD:
        row = (
            CoinTransaction.objects.filter(
                user=profile.user,
                reason=placement.reward_reason,
                created_at__gte=since,
                amount__gt=0,
            )
            .order_by("-created_at")
            .values("id", "amount")
            .first()
        )
        if row is None:
            return 0, ""
        return min(row["amount"], placement.reward_amount), f"coin_tx:{row['id']}"

    return placement.reward_amount, ""


def open_impression(
    profile: UserProfile,
    placement: AdPlacement,
    game_code: str = "",
    now: datetime | None = None,
) -> AdImpression:
    """Cấp vé cho một lượt quảng cáo. Ném :class:`Conflict` kèm mã lý do nếu không đủ điều kiện.

    Vé được tính vào trần ngay khi cấp: bỏ quảng cáo giữa chừng rồi mở lại vẫn tốn lượt.
    """
    from apps.common.exceptions import Conflict  # noqa: PLC0415 — tránh import vòng

    now = now or djtz.now()
    with transaction.atomic():
        locked = UserProfile.objects.select_for_update().get(pk=profile.pk)
        state = user_state(locked, now)
        reason = blocked_reason(locked, placement, state, now)
        if reason:
            raise Conflict(BLOCK_MESSAGES[reason], code=reason)
        amount, reward_ref = resolve_reward(locked, placement, game_code, now)
        if amount <= 0 and placement.reward_kind != AdPlacement.Reward.NONE:
            raise Conflict(BLOCK_MESSAGES[NO_REWARD_CONTEXT], code=NO_REWARD_CONTEXT)
        if reward_ref and _already_used(locked, reward_ref):
            raise Conflict(BLOCK_MESSAGES[ALREADY_REWARDED], code=ALREADY_REWARDED)
        return AdImpression.objects.create(
            user=locked.user,
            placement=placement,
            slot=placement.slot,
            reward_kind=placement.reward_kind,
            reward_amount=amount,
            reward_ref=reward_ref,
            local_date=state.local_date,
        )


def _already_used(profile: UserProfile, reward_ref: str) -> bool:
    """Một ván chỉ đổi được một lượt quảng cáo; vé đang chờ cũng tính là đã dùng."""
    return AdImpression.objects.filter(
        user=profile.user,
        reward_ref=reward_ref,
        status__in=[AdImpression.Status.PENDING, AdImpression.Status.REWARDED],
    ).exists()


def is_expired(impression: AdImpression, now: datetime) -> bool:
    return impression.created_at < now - timedelta(seconds=settings.ADS_TICKET_TTL_SEC)


def _apply_reward(profile: UserProfile, impression: AdImpression, now: datetime) -> int:
    """Cộng thưởng thật. Trả về số lượng **thực** nhận (có thể nhỏ hơn mức hứa vì trần ngày)."""
    amount = impression.reward_amount
    if impression.reward_kind == AdPlacement.Reward.COINS:
        state = user_state(profile, now)
        amount = min(amount, state.coins_left)
        if amount <= 0:
            return 0
        shop.grant_coins(
            profile,
            amount,
            reason="ad_reward",
            ref_type="ad_slot",
            ref_id=impression.slot,
        )
        return amount
    if impression.reward_kind == AdPlacement.Reward.HEARTS:
        learn.regen_hearts(profile)
        before = profile.hearts
        profile.hearts = min(learn.HEARTS_MAX, profile.hearts + amount)
        if profile.hearts == learn.HEARTS_MAX:
            profile.hearts_updated_at = now
        profile.save(update_fields=["hearts", "hearts_updated_at"])
        return profile.hearts - before
    return 0


def grant(
    impression: AdImpression,
    *,
    transaction_id: str = "",
    network: str = "",
    ad_unit: str = "",
    verified: bool = False,
    now: datetime | None = None,
) -> AdImpression:
    """Cộng thưởng cho một vé. Idempotent — gọi lại trên vé đã thưởng không cộng thêm."""
    now = now or djtz.now()
    with transaction.atomic():
        imp = AdImpression.objects.select_for_update().get(pk=impression.pk)
        if imp.status != AdImpression.Status.PENDING:
            return imp
        if is_expired(imp, now):
            imp.status = AdImpression.Status.EXPIRED
            imp.save(update_fields=["status"])
            return imp
        profile = UserProfile.objects.select_for_update().get(user=imp.user)
        granted = _apply_reward(profile, imp, now)
        imp.status = AdImpression.Status.REWARDED
        imp.granted_amount = granted
        imp.rewarded_at = now
        imp.signature_verified = verified
        if transaction_id:
            imp.ssv_transaction_id = transaction_id
        if network:
            imp.ad_network = network
        if ad_unit:
            imp.ad_unit = ad_unit
        imp.save(
            update_fields=[
                "status",
                "granted_amount",
                "rewarded_at",
                "signature_verified",
                "ssv_transaction_id",
                "ad_network",
                "ad_unit",
            ]
        )
        return imp
