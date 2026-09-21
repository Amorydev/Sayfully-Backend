"""Lõi thanh toán. CHỈ nơi này đổi quyền Premium (qua webhook / redeem đã xác thực).

Webhook idempotent theo `PaymentEvent.event_id` (unique). Redeem idempotent theo
(gift_code, user). Hết hạn xử lý *lười* ở `expire_lapsed` (gọi từ `ensure_profile`),
không cần job nền.

Quy ước mốc hạn trên `UserProfile`:
- `premium_until=None` + `is_premium=True` → trọn đời.
- Premium+ (`plus_until`) bao gồm Premium: khi grant plus thì `premium_until` cũng
  được kéo tới ít nhất bằng `plus_until` (trừ khi đã trọn đời).
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone as djtz

from apps.accounts.services import ensure_profile
from apps.common.exceptions import Conflict, NotFound

from .models import GiftCode, GiftCodeRedemption, PaymentEvent, Product, Subscription

logger = logging.getLogger(__name__)

# Tên sự kiện RevenueCat (viết hoa) + tên chung viết thường cho PayOS/gift.
GRANT_EVENTS = {
    "INITIAL_PURCHASE",
    "RENEWAL",
    "UNCANCELLATION",
    "PRODUCT_CHANGE",
    "NON_RENEWING_PURCHASE",
    "SUBSCRIPTION_EXTENDED",
    "PURCHASE",
    "PAID",
}
REVOKE_EVENTS = {"EXPIRATION", "EXPIRE", "REFUND"}
CANCEL_EVENTS = {"CANCELLATION", "CANCEL"}  # tắt tự gia hạn — quyền còn tới expires_at
GRACE_EVENTS = {"BILLING_ISSUE"}
IGNORED_EVENTS = {"TEST", "SUBSCRIPTION_PAUSED", "SUBSCRIBER_ALIAS", "TEMPORARY_ENTITLEMENT_GRANT"}

PERIOD_DAYS = {Product.Period.MONTH: 30, Product.Period.YEAR: 365}


def resolve_product(provider: str, product_code: str) -> Product | None:
    """Mã store (`store_ids[provider]`) ưu tiên, rồi tới `Product.code`."""
    if not product_code:
        return None
    return (
        Product.objects.filter(**{f"store_ids__{provider}": product_code}).first()
        or Product.objects.filter(code=product_code).first()
    )


def period_expiry(product: Product, start=None):
    """Hạn dùng tính từ kỳ gói khi cổng không báo (PayOS/gift). Trọn đời → None."""
    if product.period == Product.Period.LIFETIME:
        return None
    return (start or djtz.now()) + timedelta(days=PERIOD_DAYS.get(product.period, 30))


def _apply_grant(profile, *, tier: str, expires_at) -> None:
    lifetime = profile.is_premium and profile.premium_until is None
    if tier == Product.Tier.PLUS:
        profile.plus_until = expires_at
        if not lifetime and (profile.premium_until is None or profile.premium_until < expires_at):
            profile.premium_until = expires_at
    elif not lifetime:
        profile.premium_until = expires_at
    profile.is_premium = True
    profile.save(update_fields=["is_premium", "premium_until", "plus_until"])


def grant_premium(
    user,
    *,
    provider,
    product_code,
    expires_at,
    tier=Product.Tier.PREMIUM,
    status="active",
    store="",
    txn_id="",
    will_renew=False,
):
    """Ghi Subscription (upsert theo txn gốc nếu có) và nâng quyền trên profile."""
    fields = {
        "product_code": product_code,
        "status": status,
        "store": store,
        "expires_at": expires_at,
        "will_renew": will_renew,
    }
    existing = (
        Subscription.objects.filter(user=user, provider=provider, original_txn_id=txn_id).first()
        if txn_id
        else None
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.save(update_fields=list(fields))
    else:
        Subscription.objects.create(
            user=user, provider=provider, started_at=djtz.now(), original_txn_id=txn_id, **fields
        )
    _apply_grant(ensure_profile(user), tier=tier, expires_at=expires_at)


def grant_coin_pack(user, product: Product, *, event_id: str) -> int:
    """Gói xu mua bằng tiền: cộng xu + ghi sổ (reason=coin_pack, ref=event_id)."""
    from apps.gamification.shop import grant_coins  # noqa: PLC0415 — tránh import vòng

    profile = ensure_profile(user)
    return grant_coins(
        profile, product.coins, reason="coin_pack", ref_type="payment", ref_id=event_id
    )


def _recompute(profile, now=None) -> None:
    now = now or djtz.now()
    premium_ok = profile.is_premium and (
        profile.premium_until is None or profile.premium_until > now
    )
    plus_ok = profile.plus_until is not None and profile.plus_until > now
    if not plus_ok:
        profile.plus_until = None
    profile.is_premium = premium_ok or plus_ok
    profile.save(update_fields=["is_premium", "premium_until", "plus_until"])


def revoke_premium(user, *, provider="", txn_id="", tier=Product.Tier.PREMIUM):
    """Thu hồi: đóng Subscription tương ứng và cắt mốc hạn về hiện tại."""
    now = djtz.now()
    subs = Subscription.objects.filter(user=user, status__in=["active", "grace"])
    if provider:
        subs = subs.filter(provider=provider)
    if txn_id:
        subs = subs.filter(original_txn_id=txn_id)
    subs.update(status=Subscription.Status.EXPIRED, will_renew=False)
    profile = ensure_profile(user)
    if tier == Product.Tier.PLUS:
        profile.plus_until = now
    else:
        profile.premium_until = now
        profile.plus_until = now
    _recompute(profile, now)


def _set_subscription(user, txn_id, **fields) -> None:
    qs = Subscription.objects.filter(user=user, status__in=["active", "grace"])
    if txn_id:
        qs = qs.filter(original_txn_id=txn_id)
    qs.update(**fields)


def expire_lapsed(profile, now=None) -> bool:
    """Hạ cấp khi mốc hạn đã qua. Gọi ở `ensure_profile` — rẻ, không cần cron."""
    if not profile.is_premium:
        return False
    now = now or djtz.now()
    premium_lapsed = profile.premium_until is not None and profile.premium_until <= now
    plus_lapsed = profile.plus_until is not None and profile.plus_until <= now
    if not premium_lapsed and not plus_lapsed:
        return False
    _recompute(profile, now)
    if not profile.is_premium:
        Subscription.objects.filter(user_id=profile.user_id, status__in=["active", "grace"]).update(
            status=Subscription.Status.EXPIRED, will_renew=False
        )
    return True


def process_payment_event(
    *,
    provider,
    event_id,
    event_type,
    user,
    product_code,
    expires_at,
    payload,
    txn_id="",
    store="",
    will_renew=None,
    transferred_from=(),
):
    """Xử lý 1 sự kiện thanh toán. Gọi lại cùng event_id → không xử lý hai lần."""
    with transaction.atomic():
        event, created = PaymentEvent.objects.get_or_create(
            event_id=event_id,
            defaults={
                "provider": provider,
                "event_type": event_type,
                "user": user,
                "payload": payload,
            },
        )
        if not created and event.processed_at is not None:
            return False  # đã xử lý
        et = (event_type or "").upper()
        product = resolve_product(provider, product_code)
        if et == "TRANSFER":
            for uid in transferred_from:
                _revoke_by_user_id(uid, provider)
        elif user is None or et in IGNORED_EVENTS:
            pass
        elif et in GRANT_EVENTS and product and product.kind == Product.Kind.COINS:
            grant_coin_pack(user, product, event_id=event_id)
        elif et in GRANT_EVENTS and product is None:
            logger.warning("billing: %s %s không khớp Product nào (%s)", provider, et, product_code)
        elif et in GRANT_EVENTS:
            grant_premium(
                user,
                provider=provider,
                product_code=product.code,
                expires_at=expires_at if expires_at else period_expiry(product),
                tier=product.tier,
                store=store,
                txn_id=txn_id,
                will_renew=(
                    will_renew
                    if will_renew is not None
                    else product.period in (Product.Period.MONTH, Product.Period.YEAR)
                ),
            )
        elif et in CANCEL_EVENTS:
            _set_subscription(user, txn_id, will_renew=False)
        elif et in GRACE_EVENTS:
            _set_subscription(user, txn_id, status=Subscription.Status.GRACE)
        elif et in REVOKE_EVENTS:
            revoke_premium(
                user, provider=provider, txn_id=txn_id, tier=product.tier if product else "premium"
            )
        event.processed_at = djtz.now()
        event.save(update_fields=["processed_at"])
    return True


def _revoke_by_user_id(user_id, provider) -> None:
    from apps.accounts.models import User  # noqa: PLC0415

    u = User.objects.filter(id=user_id).first()
    if u is not None:
        revoke_premium(u, provider=provider)


def redeem_gift(user, code: str):
    gift = GiftCode.objects.filter(code=code, is_active=True).first()
    now = djtz.now()
    if (
        gift is None
        or (gift.expires_at and gift.expires_at < now)
        or gift.used_count >= gift.max_uses
    ):
        raise NotFound("Mã quà tặng không hợp lệ", code="gift_code_invalid")
    if GiftCodeRedemption.objects.filter(gift_code=gift, user=user).exists():
        raise Conflict("Bạn đã dùng mã này rồi", code="gift_code_used")

    with transaction.atomic():
        GiftCodeRedemption.objects.create(gift_code=gift, user=user)
        gift.used_count += 1
        gift.save(update_fields=["used_count"])
        profile = ensure_profile(user)
        base = now
        if profile.is_premium and profile.premium_until and profile.premium_until > now:
            base = profile.premium_until  # cộng dồn vào gói đang chạy
        expires_at = (
            None
            if profile.is_premium and profile.premium_until is None
            else (base + timedelta(days=gift.days))
        )
        grant_premium(
            user, provider="gift", product_code=f"gift_{gift.days}d", expires_at=expires_at
        )
    return gift.days, expires_at
