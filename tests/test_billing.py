"""G7 thanh toán: products, subscription, redeem, checkout, webhooks (idempotent)."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone as djtz

from apps.billing import api as bapi
from apps.billing.models import GiftCode, Product, Subscription

pytestmark = pytest.mark.django_db


@pytest.fixture
def token(api, user, password):
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


@pytest.fixture
def product():
    return Product.objects.create(
        code="premium_year", name_vi="Gói Năm", period="year", price=499000,
        original_price=999000, trial_days=7, badge_vi="TIẾT KIỆM 50%",
        features=["Mở khoá A2–C2", "Gia sư AI"], order=1,
    )


def _rc(client, secret, payload):
    return client.post(
        "/api/v1/webhooks/revenuecat", data=json.dumps(payload),
        content_type="application/json", headers={"X-Webhook-Secret": secret},
    )


# --------------------------------------------------------------- products / subscription
def test_products(api, token, product):
    body = api.get("/billing/products", token=token).json()
    assert body[0]["code"] == "premium_year" and body[0]["features"][0] == "Mở khoá A2–C2"


def test_subscription_mac_dinh_free(api, token, user):
    body = api.get("/billing/subscription", token=token).json()
    assert body["is_premium"] is False and body["product_code"] is None


# --------------------------------------------------------------- redeem
def test_redeem_hop_le(api, token, user):
    GiftCode.objects.create(code="FREE30", days=30, max_uses=5)
    body = api.post("/billing/redeem", {"code": "FREE30"}, token=token).json()
    assert body["days"] == 30 and body["is_premium"] is True
    user.profile.refresh_from_db()
    assert user.profile.is_premium is True and user.profile.premium_until is not None


def test_redeem_ma_sai_404(api, token):
    r = api.post("/billing/redeem", {"code": "NOPE"}, token=token)
    assert r.status_code == 404 and r.json()["error"]["code"] == "gift_code_invalid"


def test_redeem_lan_hai_409(api, token, user):
    GiftCode.objects.create(code="FREE30", days=30, max_uses=5)
    api.post("/billing/redeem", {"code": "FREE30"}, token=token)
    r = api.post("/billing/redeem", {"code": "FREE30"}, token=token)
    assert r.status_code == 409 and r.json()["error"]["code"] == "gift_code_used"


# --------------------------------------------------------------- checkout
def test_checkout_link(api, token, product, monkeypatch):
    monkeypatch.setattr(bapi, "create_payos_link", lambda p, u: "https://pay/xyz")
    body = api.post("/billing/payos/checkout", {"product_code": "premium_year"}, token=token).json()
    assert body["checkout_url"] == "https://pay/xyz"


def test_checkout_product_khong_ton_tai_404(api, token, monkeypatch):
    monkeypatch.setattr(bapi, "create_payos_link", lambda p, u: "x")
    r = api.post("/billing/payos/checkout", {"product_code": "nope"}, token=token)
    assert r.status_code == 404


# --------------------------------------------------------------- webhooks
def test_webhook_chu_ky_sai_401(client, settings, user):
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    r = client.post(
        "/api/v1/webhooks/revenuecat", data=json.dumps({"event": {}}),
        content_type="application/json", headers={"X-Webhook-Secret": "wrong"},
    )
    assert r.status_code == 401 and r.json()["error"]["code"] == "webhook_signature_invalid"


def test_webhook_purchase_bat_premium(client, settings, user):
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    exp_ms = int((djtz.now() + timedelta(days=365)).timestamp() * 1000)
    payload = {"event": {"id": "evt1", "type": "INITIAL_PURCHASE",
                         "app_user_id": str(user.id), "product_id": "premium_year",
                         "expiration_at_ms": exp_ms}}
    assert _rc(client, "topsecret", payload).status_code == 200
    user.profile.refresh_from_db()
    assert user.profile.is_premium is True
    assert Subscription.objects.filter(user=user).count() == 1


def test_webhook_idempotent(client, settings, user):
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    exp_ms = int((djtz.now() + timedelta(days=365)).timestamp() * 1000)
    payload = {"event": {"id": "evt1", "type": "INITIAL_PURCHASE",
                         "app_user_id": str(user.id), "product_id": "premium_year",
                         "expiration_at_ms": exp_ms}}
    _rc(client, "topsecret", payload)
    _rc(client, "topsecret", payload)  # gửi lại cùng event_id
    assert Subscription.objects.filter(user=user).count() == 1  # không xử lý hai lần
