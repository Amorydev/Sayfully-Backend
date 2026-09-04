"""Schema G7 — thanh toán."""

from datetime import datetime

from ninja import Schema


class ProductOut(Schema):
    code: str
    name_vi: str
    period: str
    price: int
    original_price: int | None
    currency: str
    trial_days: int
    badge_vi: str
    features: list[str]


class SubscriptionOut(Schema):
    is_premium: bool
    product_code: str | None
    status: str | None
    provider: str | None
    expires_at: datetime | None


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
