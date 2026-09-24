"""Gói xu bán qua Google Play (RevenueCat consumable): webhook + /billing/sync không cộng đôi."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone as djtz

from apps.billing import api as bapi
from apps.billing.models import Product
from apps.gamification.models import CoinTransaction

pytestmark = pytest.mark.django_db

SECRET = "topsecret"


@pytest.fixture(autouse=True)
def _secret(settings):
    settings.REVENUECAT_WEBHOOK_SECRET = SECRET


@pytest.fixture
def token(api, user, password):
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


@pytest.fixture
def pack():
    return Product.objects.create(
        code="coins_500",
        name_vi="500 xu",
        kind="coins",
        coins=500,
        period="one_time",
        price=19000,
        store_ids={"revenuecat": "sayfully_coins_500"},
    )


def _webhook(client, user, type_, event_id, txn="GPA.3301-0001"):
    body = {
        "event": {
            "id": event_id,
            "type": type_,
            "app_user_id": str(user.id),
            "product_id": "sayfully_coins_500",
            "transaction_id": txn,
            "original_transaction_id": txn,
            "store": "PLAY_STORE",
        }
    }
    return client.post(
        "/api/v1/webhooks/revenuecat",
        data=json.dumps(body),
        content_type="application/json",
        headers={"Authorization": SECRET},
    )


def _sync(api, token, monkeypatch, *txns):
    subscriber = {
        "entitlements": {},
        "subscriptions": {},
        "non_subscriptions": {
            "sayfully_coins_500": [
                {"id": f"rc_{t}", "store_transaction_id": t, "store": "play_store"} for t in txns
            ]
        },
    }
    monkeypatch.setattr(bapi, "fetch_subscriber", lambda uid: subscriber)
    return api.post("/billing/sync", token=token)


def _coins(user):
    user.profile.refresh_from_db()
    return user.profile.coins


def test_webhook_cong_xu_mot_lan(client, user, pack):
    assert _webhook(client, user, "NON_RENEWING_PURCHASE", "ev1").status_code == 200
    assert _webhook(client, user, "NON_RENEWING_PURCHASE", "ev1").status_code == 200
    assert _coins(user) == 500
    entry = CoinTransaction.objects.get(user=user, reason="coin_pack")
    assert (entry.ref_type, entry.ref_id) == ("store_txn", "GPA.3301-0001")


def test_sync_cong_ngay_roi_webhook_cung_giao_dich_khong_cong_doi(
    api, client, token, user, pack, monkeypatch
):
    assert _sync(api, token, monkeypatch, "GPA.3301-0001").status_code == 200
    assert _coins(user) == 500
    _webhook(client, user, "NON_RENEWING_PURCHASE", "ev-late")
    _sync(api, token, monkeypatch, "GPA.3301-0001")
    assert _coins(user) == 500


def test_hai_giao_dich_khac_nhau_cong_hai_lan(api, client, token, user, pack, monkeypatch):
    _webhook(client, user, "NON_RENEWING_PURCHASE", "ev1", txn="GPA.A")
    _sync(api, token, monkeypatch, "GPA.A", "GPA.B")
    assert _coins(user) == 1000


def test_hoan_tien_tru_xu_khong_dung_premium(client, user, pack):
    profile = user.profile
    profile.is_premium = True
    profile.premium_until = djtz.now() + timedelta(days=30)
    profile.save()
    _webhook(client, user, "NON_RENEWING_PURCHASE", "ev1")
    _webhook(client, user, "CANCELLATION", "ev2")
    _webhook(client, user, "CANCELLATION", "ev3")
    user.profile.refresh_from_db()
    assert user.profile.coins == 0 and user.profile.is_premium is True
    assert CoinTransaction.objects.filter(user=user, reason="coin_pack_refund").count() == 1


def test_hoan_tien_khi_da_tieu_bot_chi_tru_toi_so_du(client, user, pack):
    _webhook(client, user, "NON_RENEWING_PURCHASE", "ev1")
    user.profile.refresh_from_db()
    user.profile.coins = 120
    user.profile.save(update_fields=["coins"])
    _webhook(client, user, "CANCELLATION", "ev2")
    assert _coins(user) == 0
    assert CoinTransaction.objects.get(user=user, reason="coin_pack_refund").amount == -120


def test_hoan_tien_giao_dich_chua_cong_thi_bo_qua(client, user, pack):
    _webhook(client, user, "CANCELLATION", "ev1", txn="GPA.chua-co")
    assert _coins(user) == 0
    assert not CoinTransaction.objects.filter(user=user).exists()
