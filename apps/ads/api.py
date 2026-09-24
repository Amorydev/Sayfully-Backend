"""Quảng cáo — cấu hình vị trí, cấp vé và nhận thưởng sau khi mạng quảng cáo xác thực.

Luồng một lượt quảng cáo có thưởng:

1. ``GET /ads/config`` — client biết vị trí nào đang bật, còn mấy lượt hôm nay.
2. ``POST /ads/impressions`` — xin vé; server kiểm trần/khoảng cách rồi trả ``impression_id``.
   Client gắn id này vào quảng cáo (``custom_data``) trước khi hiển thị.
3. ``GET /ads/ssv`` — mạng quảng cáo gọi khi người dùng xem xong; server xác thực chữ ký
   rồi cộng thưởng. Đây là **nơi duy nhất** thưởng được cộng ở môi trường thật.
4. ``POST /ads/impressions/{id}/claim`` — client hỏi kết quả và nhận số dư mới.
"""

from datetime import timedelta

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone as djtz
from ninja import Router

from apps.accounts.services import ensure_profile
from apps.common.exceptions import NotFound
from apps.common.schemas import ErrorOut
from apps.learning import services as learn

from . import schemas as s
from . import services, ssv
from .models import AdImpression, AdPlacement

router = Router()
ssv_router = Router()


def _placement_out(
    placement: AdPlacement, state: services.AdState, reason: str | None
) -> s.AdPlacementOut:
    return s.AdPlacementOut(
        slot=placement.slot,
        title_vi=placement.title_vi,
        format=placement.format,
        reward_kind=placement.reward_kind,
        reward_amount=placement.reward_amount,
        daily_cap=placement.daily_cap,
        used_today=state.per_slot.get(placement.slot, 0),
        remaining_today=services.remaining_today(placement, state),
        cooldown_seconds=max(settings.ADS_MIN_INTERVAL_SEC, placement.cooldown_seconds),
        ad_unit_android=placement.ad_unit_android,
        ad_unit_ios=placement.ad_unit_ios,
        blocked_reason=reason,
    )


@router.get(
    "/config",
    response={200: s.AdsConfigOut, 401: ErrorOut},
    summary="Cấu hình quảng cáo",
    description=(
        "Vị trí đang bật, trần ngày và số lượt đã dùng hôm nay. Premium / tài khoản mới "
        "nhận `enabled=false` kèm `blocked_reason`. Client cache theo phiên và gọi lại khi mở app."
    ),
)
def ads_config(request):
    profile = ensure_profile(request.auth)
    now = djtz.now()
    state = services.user_state(profile, now)
    reason = services.global_block(state)
    rows = services.placements()
    return s.AdsConfigOut(
        enabled=reason is None,
        blocked_reason=reason,
        global_daily_cap=settings.ADS_GLOBAL_DAILY_CAP,
        used_today=state.total_today,
        min_interval_seconds=settings.ADS_MIN_INTERVAL_SEC,
        ticket_ttl_seconds=settings.ADS_TICKET_TTL_SEC,
        placements=[
            _placement_out(p, state, reason or services.blocked_reason(profile, p, state, now))
            for p in rows
        ],
    )


@router.post(
    "/impressions",
    response={200: s.AdTicketOut, 401: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Xin vé xem quảng cáo",
    description=(
        "Gọi ngay trước khi hiển thị quảng cáo. Trả `impression_id` để gắn vào `custom_data`. "
        "Không đủ điều kiện → 409 với `code` là lý do: `ads_disabled`, `premium`, `grace_period`, "
        "`slot_disabled`, `daily_cap`, `global_cap`, `cooldown`, `coin_cap`, `hearts_full`. "
        "Vé tính vào trần ngay khi cấp."
    ),
)
def open_impression(request, payload: s.AdTicketIn):
    profile = ensure_profile(request.auth)
    placement = AdPlacement.objects.filter(slot=payload.slot).first()
    if placement is None:
        raise NotFound("Không tìm thấy vị trí quảng cáo")
    now = djtz.now()
    impression = services.open_impression(profile, placement, payload.game_code, now)
    return s.AdTicketOut(
        impression_id=str(impression.id),
        slot=placement.slot,
        format=placement.format,
        reward_kind=placement.reward_kind,
        reward_amount=impression.reward_amount,
        ad_unit_android=placement.ad_unit_android,
        ad_unit_ios=placement.ad_unit_ios,
        custom_data=str(impression.id),
        user_id=str(profile.user_id),
        expires_at=now + timedelta(seconds=settings.ADS_TICKET_TTL_SEC),
    )


@router.post(
    "/impressions/{impression_id}/claim",
    response={200: s.AdRewardOut, 401: ErrorOut, 404: ErrorOut},
    summary="Nhận thưởng sau khi xem",
    description=(
        "Trả trạng thái vé và số dư mới. `status=pending` nghĩa là chưa có callback SSV — "
        "client chờ 1–2 giây rồi gọi lại. Gọi nhiều lần không cộng thêm thưởng."
    ),
)
def claim_impression(request, impression_id: str):
    profile = ensure_profile(request.auth)
    impression = AdImpression.objects.filter(id=impression_id, user=profile.user).first()
    if impression is None:
        raise NotFound("Không tìm thấy lượt quảng cáo")
    now = djtz.now()
    if impression.status == AdImpression.Status.PENDING:
        if settings.ADS_SSV_REQUIRED:
            if services.is_expired(impression, now):
                impression.status = AdImpression.Status.EXPIRED
                impression.save(update_fields=["status"])
        else:
            impression = services.grant(impression, now=now)
    profile.refresh_from_db()
    learn.regen_hearts(profile)
    return s.AdRewardOut(
        impression_id=str(impression.id),
        status=impression.status,
        reward_kind=impression.reward_kind,
        granted_amount=impression.granted_amount,
        coins=profile.coins,
        hearts=profile.hearts,
    )


@ssv_router.get(
    "/ssv",
    response={200: None, 400: None},
    summary="Callback SSV của mạng quảng cáo",
    description=(
        "Mạng quảng cáo gọi khi người dùng xem xong. Xác thực chữ ký ECDSA rồi cộng thưởng "
        "cho vé trong `custom_data`. Không dành cho client — không có auth, không trả dữ liệu."
    ),
    auth=None,
)
def ssv_callback(request):
    try:
        params = ssv.verify(request.META.get("QUERY_STRING", ""))
    except ssv.SsvError:
        return HttpResponse(status=400)
    impression = AdImpression.objects.filter(id=params.get("custom_data", "")).first()
    if impression is None:
        return HttpResponse(status=400)
    transaction_id = params.get("transaction_id", "")
    if (
        transaction_id
        and AdImpression.objects.filter(ssv_transaction_id=transaction_id)
        .exclude(pk=impression.pk)
        .exists()
    ):
        return HttpResponse(status=200)
    services.grant(
        impression,
        transaction_id=transaction_id,
        network=params.get("ad_network", ""),
        ad_unit=params.get("ad_unit", ""),
        verified=settings.ADS_SSV_REQUIRED,
    )
    return HttpResponse(status=200)
