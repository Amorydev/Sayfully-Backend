"""G7 — 6 endpoint thanh toán: 4 dưới /billing (Bearer) + 2 webhook (không auth).

CHỈ webhook/redeem (đã xác thực server) đổi `is_premium`. Webhook idempotent theo
`event_id`. Chữ ký webhook và link PayOS là hàm cấp module — test thay bằng hàm giả.
"""

import json
from datetime import UTC, datetime

from django.conf import settings
from ninja import Router

from apps.accounts.models import User
from apps.accounts.services import ensure_profile
from apps.common.exceptions import NotFound, Unauthorized
from apps.common.schemas import ErrorOut

from . import schemas as s
from . import services
from .models import Product, Subscription

billing_router = Router()
webhooks_router = Router()


def create_payos_link(product: Product, user: User) -> str:
    """Tạo link thanh toán PayOS. Chưa cấu hình → báo lỗi rõ."""
    key = getattr(settings, "PAYOS_API_KEY", "")
    if not key:
        raise NotFound("Chưa cấu hình PayOS", code="service_unavailable", status_code=503)
    # production: gọi SDK PayOS tạo payment link theo product.price
    return f"https://pay.payos.vn/web/{product.code}"


def _ms_to_dt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=UTC) if ms else None


def _iso(v):
    try:
        return datetime.fromisoformat(v) if v else None
    except (ValueError, TypeError):
        return None


def _extract(body: dict) -> dict:
    ev = body.get("event", body)  # RevenueCat lồng dưới "event"
    return {
        "event_id": str(ev.get("id") or ev.get("event_id") or ""),
        "event_type": ev.get("type") or ev.get("event_type") or "",
        "app_user_id": ev.get("app_user_id") or ev.get("user_id"),
        "product_code": ev.get("product_id") or ev.get("product_code") or "",
        "expires_at": _ms_to_dt(ev.get("expiration_at_ms")) or _iso(ev.get("expires_at")),
    }


def _verify(request, secret_setting: str):
    secret = getattr(settings, secret_setting, "")
    if not secret or request.headers.get("X-Webhook-Secret", "") != secret:
        raise Unauthorized("Chữ ký webhook không hợp lệ", code="webhook_signature_invalid")


# =============================================================== /billing (Bearer)
@billing_router.get(
    "/products",
    response={200: list[s.ProductOut], 401: ErrorOut},
    summary="Danh sách gói Premium",
    description="Gói + giá + đặc quyền để dựng paywall.",
)
def products(request):
    ensure_profile(request.auth)
    return [
        s.ProductOut(
            code=p.code,
            name_vi=p.name_vi,
            period=p.period,
            price=p.price,
            original_price=p.original_price,
            currency=p.currency,
            trial_days=p.trial_days,
            badge_vi=p.badge_vi,
            features=p.features or [],
        )
        for p in Product.objects.filter(is_active=True).order_by("order")
    ]


@billing_router.get(
    "/subscription",
    response={200: s.SubscriptionOut, 401: ErrorOut},
    summary="Trạng thái Premium",
    description="Gói đang hiệu lực (nếu có) + cờ `is_premium`.",
)
def subscription(request):
    user = request.auth
    profile = ensure_profile(user)
    sub = (
        Subscription.objects.filter(user=user, status=Subscription.Status.ACTIVE)
        .order_by("-started_at")
        .first()
    )
    return s.SubscriptionOut(
        is_premium=profile.is_premium,
        product_code=sub.product_code if sub else None,
        status=sub.status if sub else None,
        provider=sub.provider if sub else None,
        expires_at=sub.expires_at if sub else None,
    )


@billing_router.post(
    "/redeem",
    response={200: s.RedeemResultOut, 401: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Đổi mã quà tặng",
    description="Mã hợp lệ → cộng ngày Premium. Mỗi mã 1 lần/user (`gift_code_used`).",
)
def redeem(request, payload: s.RedeemIn):
    user = request.auth
    profile = ensure_profile(user)
    days, expires_at = services.redeem_gift(user, payload.code)
    profile.refresh_from_db()
    return s.RedeemResultOut(
        product_code=f"gift_{days}d", days=days, expires_at=expires_at, is_premium=profile.is_premium
    )


@billing_router.post(
    "/payos/checkout",
    response={200: s.CheckoutOut, 401: ErrorOut, 404: ErrorOut, 503: ErrorOut},
    summary="Tạo link thanh toán PayOS (web)",
    description="Trả `checkout_url` để redirect. Premium chỉ bật sau khi webhook xác nhận.",
)
def payos_checkout(request, payload: s.CheckoutIn):
    user = request.auth
    ensure_profile(user)
    product = Product.objects.filter(code=payload.product_code, is_active=True).first()
    if product is None:
        raise NotFound("Không tìm thấy gói")
    return s.CheckoutOut(checkout_url=create_payos_link(product, user))


# =============================================================== /webhooks (không auth)
def _handle_webhook(request, provider, secret_setting):
    _verify(request, secret_setting)
    try:
        payload = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        payload = {}
    data = _extract(payload)
    user = User.objects.filter(id=data["app_user_id"]).first() if data["app_user_id"] else None
    if data["event_id"]:
        services.process_payment_event(
            provider=provider,
            event_id=f"{provider}:{data['event_id']}",
            event_type=data["event_type"],
            user=user,
            product_code=data["product_code"],
            expires_at=data["expires_at"],
            payload=payload,
        )
    return {"ok": True}


@webhooks_router.post(
    "/revenuecat",
    auth=None,
    response={200: dict, 401: ErrorOut},
    summary="Webhook RevenueCat",
    description="Xác thực chữ ký · idempotent theo `event_id` · đổi `is_premium`.",
)
def revenuecat_webhook(request):
    return _handle_webhook(request, "revenuecat", "REVENUECAT_WEBHOOK_SECRET")


@webhooks_router.post(
    "/payos",
    auth=None,
    response={200: dict, 401: ErrorOut},
    summary="Webhook PayOS",
    description="Xác thực chữ ký · idempotent theo `event_id` · đổi `is_premium`.",
)
def payos_webhook(request):
    return _handle_webhook(request, "payos", "PAYOS_WEBHOOK_SECRET")
