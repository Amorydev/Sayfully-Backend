"""Schema G7 — thanh toán."""

from datetime import datetime

from ninja import Schema


class ProductOut(Schema):
    code: str
    name_vi: str
    kind: str = "premium"  # premium | coins
    tier: str = "premium"  # premium | plus
    coins: int = 0  # kind=coins: số xu nhận
    period: str
    store_product_id: str  # mã sản phẩm trên RevenueCat/store để app khớp offering
    price: int
    original_price: int | None
    currency: str
    trial_days: int
    badge_vi: str
    features: list[str]


class SubscriptionOut(Schema):
    is_premium: bool
    tier: str = "premium"  # plus khi Premium+ còn hạn
    premium_until: datetime | None = None  # null khi trọn đời (hoặc chưa Premium)
    product_code: str | None
    status: str | None
    provider: str | None
    store: str | None = None  # play_store | app_store | web
    expires_at: datetime | None
    will_renew: bool = False


class RedeemIn(Schema):
    code: str


class RedeemResultOut(Schema):
    product_code: str
    days: int
    expires_at: datetime | None
    is_premium: bool


class CheckoutIn(Schema):
    product_code: str


class CheckoutOut(Schema):
    checkout_url: str
