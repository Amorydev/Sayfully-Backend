"""G7 thanh toán: products, subscription, redeem, checkout, webhooks (idempotent)."""

import json
from datetime import timedelta

import pytest
import time_machine
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
        content_type="application/json", headers={"Authorization": secret},
    )


def _event(user, type_, product="premium_year", days=365, **extra):
    ev = {"id": extra.pop("id", f"{type_}-{product}"), "type": type_,
          "app_user_id": str(user.id), "product_id": product,
          "original_transaction_id": extra.pop("txn", "GPA.1"), "store": "PLAY_STORE"}
    if days is not None:
        ev["expiration_at_ms"] = int((djtz.now() + timedelta(days=days)).timestamp() * 1000)
    ev.update(extra)
    return {"event": ev}


# --------------------------------------------------------------- products / subscription
def test_products(api, token, product):
    body = api.get("/billing/products", token=token).json()
    assert body[0]["code"] == "premium_year" and body[0]["features"][0] == "Mở khoá A2–C2"
    assert body[0]["tier"] == "premium" and body[0]["store_product_id"] == "premium_year"


def test_products_store_product_id_tu_store_ids(api, token, product):
    product.store_ids = {"revenuecat": "sayfully_premium_year"}
    product.save()
    body = api.get("/billing/products", token=token).json()
    assert body[0]["store_product_id"] == "sayfully_premium_year"


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
        content_type="application/json", headers={"Authorization": "wrong"},
    )
    assert r.status_code == 401 and r.json()["error"]["code"] == "webhook_signature_invalid"


def test_webhook_purchase_bat_premium(client, settings, user, product):
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    exp_ms = int((djtz.now() + timedelta(days=365)).timestamp() * 1000)
    payload = {"event": {"id": "evt1", "type": "INITIAL_PURCHASE",
                         "app_user_id": str(user.id), "product_id": "premium_year",
                         "expiration_at_ms": exp_ms}}
    assert _rc(client, "topsecret", payload).status_code == 200
    user.profile.refresh_from_db()
    assert user.profile.is_premium is True
    assert Subscription.objects.filter(user=user).count() == 1


def test_webhook_idempotent(client, settings, user, product):
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    exp_ms = int((djtz.now() + timedelta(days=365)).timestamp() * 1000)
    payload = {"event": {"id": "evt1", "type": "INITIAL_PURCHASE",
                         "app_user_id": str(user.id), "product_id": "premium_year",
                         "expiration_at_ms": exp_ms}}
    _rc(client, "topsecret", payload)
    _rc(client, "topsecret", payload)  # gửi lại cùng event_id
    assert Subscription.objects.filter(user=user).count() == 1  # không xử lý hai lần


def test_webhook_bearer_prefix_duoc_chap_nhan(client, settings, user, product):
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    r = _rc(client, "Bearer topsecret", _event(user, "INITIAL_PURCHASE"))
    assert r.status_code == 200
    user.profile.refresh_from_db()
    assert user.profile.is_premium is True


def test_webhook_map_store_id(client, settings, user, product):
    product.store_ids = {"revenuecat": "sayfully_premium_year"}
    product.save()
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    _rc(client, "topsecret", _event(user, "INITIAL_PURCHASE", product="sayfully_premium_year"))
    sub = Subscription.objects.get(user=user)
    assert sub.product_code == "premium_year" and sub.store == "play_store"
    assert sub.will_renew is True and sub.original_txn_id == "GPA.1"


def test_webhook_tron_doi_khong_co_han(client, settings, user):
    Product.objects.create(code="premium_lifetime", name_vi="Trọn đời", period="lifetime",
                           price=999000)
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    r = _rc(client, "topsecret",
            _event(user, "NON_RENEWING_PURCHASE", product="premium_lifetime", days=None))
    assert r.status_code == 200
    user.profile.refresh_from_db()
    assert user.profile.is_premium is True and user.profile.premium_until is None
    sub = Subscription.objects.get(user=user)
    assert sub.expires_at is None and sub.will_renew is False


def test_webhook_renewal_cap_nhat_cung_subscription(client, settings, user, product):
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    _rc(client, "topsecret", _event(user, "INITIAL_PURCHASE", id="e1", days=30))
    _rc(client, "topsecret", _event(user, "RENEWAL", id="e2", days=60))
    assert Subscription.objects.filter(user=user).count() == 1
    user.profile.refresh_from_db()
    assert user.profile.premium_until > djtz.now() + timedelta(days=59)


def test_webhook_cancellation_giu_quyen_toi_het_han(client, settings, user, product):
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    _rc(client, "topsecret", _event(user, "INITIAL_PURCHASE", id="e1"))
    _rc(client, "topsecret", _event(user, "CANCELLATION", id="e2"))
    user.profile.refresh_from_db()
    sub = Subscription.objects.get(user=user)
    assert user.profile.is_premium is True
    assert sub.status == "active" and sub.will_renew is False


def test_webhook_billing_issue_grace(client, settings, user, product):
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    _rc(client, "topsecret", _event(user, "INITIAL_PURCHASE", id="e1"))
    _rc(client, "topsecret", _event(user, "BILLING_ISSUE", id="e2"))
    assert Subscription.objects.get(user=user).status == "grace"
    user.profile.refresh_from_db()
    assert user.profile.is_premium is True


def test_webhook_expiration_thu_hoi(api, token, client, settings, user, product):
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    _rc(client, "topsecret", _event(user, "INITIAL_PURCHASE", id="e1"))
    _rc(client, "topsecret", _event(user, "EXPIRATION", id="e2"))
    user.profile.refresh_from_db()
    assert user.profile.is_premium is False
    assert Subscription.objects.get(user=user).status == "expired"
    body = api.get("/billing/subscription", token=token).json()
    assert body["is_premium"] is False and body["product_code"] is None


def test_webhook_transfer_thu_hoi_user_cu(client, settings, user, product, password):
    from apps.accounts.models import User

    other = User.objects.create_user(email="khac@example.com", password=password)
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    _rc(client, "topsecret", _event(user, "INITIAL_PURCHASE", id="e1"))
    payload = _event(other, "TRANSFER", id="e3", days=None,
                     transferred_from=[str(user.id)], transferred_to=[str(other.id)])
    assert _rc(client, "topsecret", payload).status_code == 200
    user.profile.refresh_from_db()
    assert user.profile.is_premium is False


def test_webhook_san_pham_la_khong_grant(client, settings, user):
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    assert _rc(client, "topsecret", _event(user, "INITIAL_PURCHASE", product="nope")).status_code == 200
    user.profile.refresh_from_db()
    assert user.profile.is_premium is False


def test_webhook_test_event_khong_lam_gi(client, settings, user, product):
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    assert _rc(client, "topsecret", _event(user, "TEST", id="t")).status_code == 200
    user.profile.refresh_from_db()
    assert user.profile.is_premium is False


def test_webhook_goi_xu_cong_xu(client, settings, user):
    Product.objects.create(code="coins_500", name_vi="500 xu", period="one_time",
                           price=19000, kind="coins", coins=500)
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    _rc(client, "topsecret", _event(user, "NON_RENEWING_PURCHASE", product="coins_500", days=None))
    user.profile.refresh_from_db()
    assert user.profile.coins == 500 and user.profile.is_premium is False


def test_webhook_premium_plus_keo_ca_hai_moc(client, settings, user):
    Product.objects.create(code="plus_month", name_vi="Premium+ Tháng", period="month",
                           price=149000, tier="plus")
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    _rc(client, "topsecret", _event(user, "INITIAL_PURCHASE", product="plus_month", days=30))
    user.profile.refresh_from_db()
    assert user.profile.is_premium is True
    assert user.profile.plus_until is not None
    assert user.profile.premium_until == user.profile.plus_until


# --------------------------------------------------------------- hết hạn lười
def test_subscription_out_du_truong(api, token, client, settings, user, product):
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    _rc(client, "topsecret", _event(user, "INITIAL_PURCHASE"))
    body = api.get("/billing/subscription", token=token).json()
    assert body["is_premium"] is True and body["tier"] == "premium"
    assert body["store"] == "play_store" and body["will_renew"] is True
    assert body["premium_until"] is not None and body["expires_at"] is not None


def _login(api, user, password):
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


def test_gift_het_han_tu_ha_cap(api, user, password):
    GiftCode.objects.create(code="FREE7", days=7, max_uses=5)
    with time_machine.travel("2026-09-01 08:00 +0000", tick=False):
        token = _login(api, user, password)
        api.post("/billing/redeem", {"code": "FREE7"}, token=token)
        assert api.get("/billing/subscription", token=token).json()["is_premium"] is True
    with time_machine.travel("2026-09-09 08:00 +0000", tick=False):
        token = _login(api, user, password)
        body = api.get("/billing/subscription", token=token).json()
    assert body["is_premium"] is False and body["product_code"] is None
    user.profile.refresh_from_db()
    assert user.profile.is_premium is False
    assert Subscription.objects.get(user=user).status == "expired"


def test_gift_cong_don_vao_goi_dang_chay(api, user, password):
    GiftCode.objects.create(code="A7", days=7)
    GiftCode.objects.create(code="B7", days=7)
    with time_machine.travel("2026-09-01 08:00 +0000", tick=False):
        token = _login(api, user, password)
        api.post("/billing/redeem", {"code": "A7"}, token=token)
        body = api.post("/billing/redeem", {"code": "B7"}, token=token).json()
    assert body["expires_at"].startswith("2026-09-15")


def test_tron_doi_khong_bao_gio_het_han(api, client, settings, user, password):
    Product.objects.create(code="premium_lifetime", name_vi="Trọn đời", period="lifetime",
                           price=999000)
    settings.REVENUECAT_WEBHOOK_SECRET = "topsecret"
    _rc(client, "topsecret",
        _event(user, "NON_RENEWING_PURCHASE", product="premium_lifetime", days=None))
    with time_machine.travel("2036-01-01 08:00 +0000", tick=False):
        token = _login(api, user, password)
        body = api.get("/billing/subscription", token=token).json()
    assert body["is_premium"] is True and body["premium_until"] is None


# --------------------------------------------------------------- sync RevenueCat
def _subscriber(product="sayfully_premium_year", days=365, ent="premium", **sub_extra):
    exp = None if days is None else (djtz.now() + timedelta(days=days)).isoformat().replace("+00:00", "Z")
    return {
        "entitlements": {ent: {"expires_date": exp, "product_identifier": product,
                               "purchase_date": "2026-09-01T00:00:00Z"}},
        "subscriptions": {product: {"expires_date": exp, "store": "play_store",
                                    "unsubscribe_detected_at": None,
                                    "billing_issues_detected_at": None, **sub_extra}},
        "non_subscriptions": {},
    }


@pytest.fixture
def rc_product(product):
    product.store_ids = {"revenuecat": "sayfully_premium_year"}
    product.save()
    return product


def _sync(api, token, monkeypatch, subscriber):
    monkeypatch.setattr(bapi, "fetch_subscriber", lambda uid: subscriber)
    return api.post("/billing/sync", token=token)


def test_sync_entitlement_con_han_bat_premium(api, token, user, rc_product, monkeypatch):
    body = _sync(api, token, monkeypatch, _subscriber()).json()
    assert body["is_premium"] is True and body["store"] == "play_store" and body["will_renew"] is True
    sub = Subscription.objects.get(user=user)
    assert sub.provider == "revenuecat" and sub.original_txn_id == "rc:sayfully_premium_year"


def test_sync_goi_lai_khong_tao_dong_moi(api, token, user, rc_product, monkeypatch):
    _sync(api, token, monkeypatch, _subscriber())
    _sync(api, token, monkeypatch, _subscriber())
    assert Subscription.objects.filter(user=user).count() == 1


def test_sync_tron_doi(api, token, user, monkeypatch):
    Product.objects.create(code="premium_lifetime", name_vi="Trọn đời", period="lifetime",
                           price=999000, store_ids={"revenuecat": "sayfully_premium_lifetime"})
    body = _sync(api, token, monkeypatch, _subscriber("sayfully_premium_lifetime", days=None)).json()
    assert body["is_premium"] is True and body["premium_until"] is None and body["will_renew"] is False


def test_sync_het_han_thu_hoi(api, token, user, rc_product, monkeypatch):
    _sync(api, token, monkeypatch, _subscriber())
    body = _sync(api, token, monkeypatch, _subscriber(days=-1)).json()
    assert body["is_premium"] is False and body["product_code"] is None
    assert Subscription.objects.get(user=user).status == "expired"


def test_sync_khong_con_entitlement_thu_hoi(api, token, user, rc_product, monkeypatch):
    _sync(api, token, monkeypatch, _subscriber())
    body = _sync(api, token, monkeypatch, {"entitlements": {}, "subscriptions": {}}).json()
    assert body["is_premium"] is False


def test_sync_tat_gia_han_va_loi_thanh_toan(api, token, user, rc_product, monkeypatch):
    body = _sync(api, token, monkeypatch, _subscriber(
        unsubscribe_detected_at="2026-09-10T00:00:00Z", billing_issues_detected_at="2026-09-11T00:00:00Z",
    )).json()
    assert body["is_premium"] is True and body["will_renew"] is False and body["status"] == "grace"


def test_sync_subscriber_chua_ton_tai_tra_free(api, token, user, monkeypatch):
    body = _sync(api, token, monkeypatch, None).json()
    assert body["is_premium"] is False


def test_sync_san_pham_la_bo_qua(api, token, user, monkeypatch):
    body = _sync(api, token, monkeypatch, _subscriber("unknown_product")).json()
    assert body["is_premium"] is False


def test_sync_khong_dung_gift_dang_chay(api, token, user, monkeypatch):
    GiftCode.objects.create(code="FREE30", days=30)
    api.post("/billing/redeem", {"code": "FREE30"}, token=token)
    body = _sync(api, token, monkeypatch, {"entitlements": {}, "subscriptions": {}}).json()
    assert body["is_premium"] is True and body["provider"] == "gift"


def test_sync_chua_cau_hinh_503(api, token, user, settings):
    settings.REVENUECAT_API_KEY = ""
    r = api.post("/billing/sync", token=token)
    assert r.status_code == 503 and r.json()["error"]["code"] == "store_sync_failed"


def test_sync_revenuecat_loi_503(api, token, user, monkeypatch):
    from apps.billing.revenuecat import StoreSyncFailed

    def boom(uid):
        raise StoreSyncFailed("RevenueCat trả 500")

    monkeypatch.setattr(bapi, "fetch_subscriber", boom)
    r = api.post("/billing/sync", token=token)
    assert r.status_code == 503 and r.json()["error"]["code"] == "store_sync_failed"


def test_sync_rate_limit(api, token, user, settings, monkeypatch):
    settings.RATELIMIT_ENABLE = True
    monkeypatch.setattr(bapi, "fetch_subscriber", lambda uid: None)
    codes = [api.post("/billing/sync", token=token).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429
