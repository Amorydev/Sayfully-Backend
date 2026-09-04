"""Lõi thanh toán. CHỈ nơi này đổi `is_premium` (qua webhook / redeem đã xác thực).

Webhook idempotent theo `PaymentEvent.event_id` (unique). Redeem idempotent theo
(gift_code, user).
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone as djtz

from apps.accounts.services import ensure_profile
from apps.common.exceptions import Conflict, NotFound

from .models import GiftCode, GiftCodeRedemption, PaymentEvent, Subscription

_GRANT_EVENTS = {"purchase", "renewal", "initial_purchase", "product_change", "uncancellation"}
_REVOKE_EVENTS = {"expiration", "cancel", "expire"}


def grant_premium(user, *, provider, product_code, expires_at, status="active", store="", txn_id=""):
    Subscription.objects.create(
        user=user,
        provider=provider,
        product_code=product_code,
        status=status,
        store=store,
        started_at=djtz.now(),
        expires_at=expires_at,
        original_txn_id=txn_id,
    )
    profile = ensure_profile(user)
    profile.is_premium = True
    profile.premium_until = expires_at
    profile.save(update_fields=["is_premium", "premium_until"])


def revoke_premium(user):
    profile = ensure_profile(user)
    profile.is_premium = False
    profile.save(update_fields=["is_premium"])


def process_payment_event(
    *, provider, event_id, event_type, user, product_code, expires_at, payload
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
        if user is not None:
            et = event_type.lower()
            if et in _GRANT_EVENTS and product_code and expires_at:
                grant_premium(
                    user, provider=provider, product_code=product_code, expires_at=expires_at
                )
            elif et in _REVOKE_EVENTS:
                revoke_premium(user)
        event.processed_at = djtz.now()
        event.save(update_fields=["processed_at"])
    return True


def redeem_gift(user, code: str):
    gift = GiftCode.objects.filter(code=code, is_active=True).first()
    now = djtz.now()
    if gift is None or (gift.expires_at and gift.expires_at < now) or gift.used_count >= gift.max_uses:
        raise NotFound("Mã quà tặng không hợp lệ", code="gift_code_invalid")
    if GiftCodeRedemption.objects.filter(gift_code=gift, user=user).exists():
        raise Conflict("Bạn đã dùng mã này rồi", code="gift_code_used")

    with transaction.atomic():
        GiftCodeRedemption.objects.create(gift_code=gift, user=user)
        gift.used_count += 1
        gift.save(update_fields=["used_count"])
        expires_at = now + timedelta(days=gift.days)
        grant_premium(
            user, provider="gift", product_code=f"gift_{gift.days}d", expires_at=expires_at
        )
    return gift.days, expires_at
