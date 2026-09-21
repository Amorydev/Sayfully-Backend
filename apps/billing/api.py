"""G7 — 6 endpoint thanh toán: 4 dưới /billing (Bearer) + 2 webhook (không auth).

CHỈ webhook/redeem (đã xác thực server) đổi `is_premium`. Webhook idempotent theo
`event_id`. Chữ ký webhook và link PayOS là hàm cấp module — test thay bằng hàm giả.
"""

import json
from datetime import UTC, datetime

from django.conf import settings
from django.utils import timezone as djtz
from django_ratelimit.decorators import ratelimit
from ninja import Router

from apps.accounts.models import User
from apps.accounts.services import ensure_profile
from apps.common.exceptions import NotFound, Unauthorized
from apps.common.schemas import ErrorOut

from . import schemas as s
from . import services
from .models import Product, Subscription
from .revenuecat import fetch_subscriber

billing_router = Router()
webhooks_router = Router()
RATE_SYNC = "10/m"  # mỗi lần gọi là một request tới RevenueCat


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


_STORES = {"PLAY_STORE": "play_store", "APP_STORE": "app_store", "MAC_APP_STORE": "app_store"}


def _extract(body: dict) -> dict:
    ev = body.get("event", body)  # RevenueCat lồng dưới "event"
    return {
        "event_id": str(ev.get("id") or ev.get("event_id") or ""),
        "event_type": ev.get("type") or ev.get("event_type") or "",
        "app_user_id": ev.get("app_user_id") or ev.get("user_id"),
        "product_code": ev.get("product_id") or ev.get("product_code") or "",
        "expires_at": _ms_to_dt(ev.get("expiration_at_ms")) or _iso(ev.get("expires_at")),
        "txn_id": str(ev.get("original_transaction_id") or ev.get("transaction_id") or ""),
        "store": _STORES.get(str(ev.get("store") or "").upper(), ev.get("store") or ""),
        "transferred_from": ev.get("transferred_from") or [],
    }


def _verify(request, secret_setting: str):
    """RevenueCat gửi đúng chuỗi cấu hình (có thể kèm `Bearer `) trong `Authorization`."""
    secret = getattr(settings, secret_setting, "")
    sent = request.headers.get("Authorization", "") or request.headers.get("X-Webhook-Secret", "")
    if sent.startswith("Bearer "):
        sent = sent[7:]
    if not secret or sent != secret:
        raise Unauthorized("Chữ ký webhook không hợp lệ", code="webhook_signature_invalid")


# =============================================================== /billing (Bearer)
@billing_router.get(
    "/products",
    response={200: list[s.ProductOut], 401: ErrorOut},
    summary="Danh sách gói Premium / gói xu",
    description="Gói + giá + đặc quyền để dựng paywall. `kind=coins` là gói xu mua bằng tiền.",
)
def products(request, kind: str | None = None):
    ensure_profile(request.auth)
    qs = Product.objects.filter(is_active=True).order_by("order")
    if kind:
        qs = qs.filter(kind=kind)
    return [
        s.ProductOut(
            code=p.code,
            name_vi=p.name_vi,
            kind=p.kind,
            tier=p.tier,
            coins=p.coins,
            period=p.period,
            store_product_id=(p.store_ids or {}).get("revenuecat") or p.code,
            price=p.price,
            original_price=p.original_price,
            currency=p.currency,
            trial_days=p.trial_days,
            badge_vi=p.badge_vi,
            features=[_feature(f) for f in p.features or []],
        )
        for p in qs
    ]


def _feature(raw) -> s.ProductFeatureOut:
    """`features` seed cũ là chuỗi, mới là {title, description, icon_url}."""
    if isinstance(raw, dict):
        return s.ProductFeatureOut(
            title=str(raw.get("title", "")),
            description=str(raw.get("description", "")),
            icon_url=_icon_url(raw.get("icon_url")),
        )
    return s.ProductFeatureOut(title=str(raw))


def _icon_url(value) -> str | None:
    """URL đầy đủ (http…) giữ nguyên; path tương đối thì ghép R2 base."""
    if not value:
        return None
    value = str(value)
    return value if value.startswith("http") else f"{settings.R2_PUBLIC_BASE.rstrip('/')}/{value}"


@billing_router.get(
    "/subscription",
    response={200: s.SubscriptionOut, 401: ErrorOut},
    summary="Trạng thái Premium",
    description=(
        "Gói đang hiệu lực (nếu có) + cờ `is_premium`. `premium_until=null` khi trọn đời; "
        "`tier=plus` khi Premium+ còn hạn. `store` để app mở đúng trang quản lý gói."
    ),
)
def subscription(request):
    return _subscription_out(request.auth)


@billing_router.post(
    "/sync",
    response={200: s.SubscriptionOut, 401: ErrorOut, 429: ErrorOut, 503: ErrorOut},
    summary="Đối chiếu quyền với RevenueCat",
    description=(
        "App gọi sau khi store xác nhận mua / khôi phục. Server hỏi RevenueCat REST bằng secret "
        "key rồi grant/thu hồi như webhook — không tin CustomerInfo từ client. Subscriber chưa "
        "tồn tại → trả trạng thái hiện tại. 503 `store_sync_failed` khi RevenueCat không phản hồi."
    ),
)
@ratelimit(key="user", rate=RATE_SYNC, method="POST", block=True)
def sync(request):
    user = request.auth
    ensure_profile(user)
    subscriber = fetch_subscriber(str(user.id))
    if subscriber is not None:
        services.sync_from_store(user, subscriber)
    return _subscription_out(user)


def _subscription_out(user) -> s.SubscriptionOut:
    profile = ensure_profile(user)
    sub = (
        Subscription.objects.filter(user=user, status__in=["active", "grace"])
        .order_by("-started_at")
        .first()
    )
    return s.SubscriptionOut(
        is_premium=profile.is_premium,
        tier="plus" if profile.plus_until and profile.plus_until > djtz.now() else "premium",
        premium_until=profile.premium_until if profile.is_premium else None,
        product_code=sub.product_code if sub else None,
        status=sub.status if sub else None,
        provider=sub.provider if sub else None,
        store=sub.store if sub else None,
        expires_at=sub.expires_at if sub else None,
        will_renew=sub.will_renew if sub else False,
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
        product_code=f"gift_{days}d",
        days=days,
        expires_at=expires_at,
        is_premium=profile.is_premium,
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
            txn_id=data["txn_id"],
            store=data["store"],
            transferred_from=data["transferred_from"],
        )
    return {"ok": True}


@webhooks_router.post(
    "/revenuecat",
    auth=None,
    response={200: dict, 401: ErrorOut},
    summary="Webhook RevenueCat",
    description=(
        "Header `Authorization` = secret cấu hình · idempotent theo `event_id` · "
        "map `product_id` qua `Product.store_ids.revenuecat`. INITIAL_PURCHASE/RENEWAL/"
        "UNCANCELLATION/PRODUCT_CHANGE/NON_RENEWING_PURCHASE → grant · CANCELLATION → "
        "chỉ tắt `will_renew` · BILLING_ISSUE → grace · EXPIRATION → thu hồi · TRANSFER → "
        "thu hồi user cũ."
    ),
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
