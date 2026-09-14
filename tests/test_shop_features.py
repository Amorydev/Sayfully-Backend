"""C50 Cửa hàng mở rộng: khuyến mãi, boost XP, combo, rương, hồi sinh streak, Premium theo xu,
trang trí, wishlist, ví, gợi ý kiếm xu, gói xu qua webhook, Premium +% xu."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone as djtz

from apps.billing.models import Product
from apps.billing.services import process_payment_event
from apps.gamification import shop
from apps.gamification.models import (
    Challenge,
    CoinTransaction,
    Game,
    ShopItem,
    ShopWishlist,
    UserCosmetic,
)
from apps.learning import services as learn
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


@pytest.fixture
def token(api, user, password):
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


def _item(code, cost, effect, **kw):
    return ShopItem.objects.create(
        code=code, title_vi=code, description_vi="x", cost_coins=cost, effect=effect, **kw
    )


def _buy(client, token, item_id, key="k1"):
    return client.post(
        "/api/v1/shop/purchase",
        data=json.dumps({"item_id": item_id}),
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
    )


def _rich(user, coins=5000):
    user.profile.coins = coins
    user.profile.save()
    return user.profile


# --------------------------------------------------------------- giá / khuyến mãi
def test_items_tra_gia_sau_khuyen_mai(api, token):
    _item("sale", 200, {"hearts": 5}, discount_pct=25)
    _item(
        "expired", 200, {"hearts": 5}, discount_pct=50, sale_until=djtz.now() - timedelta(hours=1)
    )
    body = {it["code"]: it for it in api.get("/shop/items", token=token).json()}
    assert body["sale"]["price_coins"] == 150 and body["sale"]["discount_pct"] == 25
    assert body["expired"]["price_coins"] == 200 and body["expired"]["discount_pct"] == 0


def test_mua_tru_gia_khuyen_mai(client, token, user):
    item = _item("sale", 200, {"streak_freeze": 1}, discount_pct=25)
    _rich(user, 300)
    r = _buy(client, token, item.id)
    assert r.status_code == 200 and r.json()["coins_spent"] == 150 and r.json()["balance"] == 150


# --------------------------------------------------------------- xp boost
def test_xp_boost_cong_don_va_nhan_doi_xp(client, token, user):
    item = _item("xp_boost", 120, {"xp_boost": 15})
    profile = _rich(user)
    assert _buy(client, token, item.id, "a").status_code == 200
    assert _buy(client, token, item.id, "b").status_code == 200
    profile.refresh_from_db()
    remaining = profile.xp_boost_until - djtz.now()
    assert timedelta(minutes=29) < remaining <= timedelta(minutes=30)
    reward = learn.record(profile, xp=10)
    assert reward.xp_earned == 20
    profile.xp_boost_until = djtz.now() - timedelta(seconds=1)
    profile.save()
    assert learn.record(profile, xp=10).xp_earned == 10


# --------------------------------------------------------------- combo
def test_combo_ap_dung_moi_hieu_ung_va_khong_chan_khi_tim_day(client, token, user):
    item = _item("bundle", 500, {"streak_freeze": 2, "hearts": 5}, category="bundle")
    profile = _rich(user)
    profile.hearts = 5
    profile.save()
    r = _buy(client, token, item.id)
    assert r.status_code == 200
    assert r.json()["effect"] == {"streak_freeze": 2, "hearts": 0}
    profile.refresh_from_db()
    assert profile.streak_freezes == 2


# --------------------------------------------------------------- rương may mắn
def test_ruong_may_man_tra_phan_thuong_va_idempotent(client, token, user, monkeypatch):
    item = _item("mystery_box", 120, {"mystery_box": 1}, category="special")
    profile = _rich(user, 200)
    monkeypatch.setattr(shop, "roll_mystery_box", lambda rng=None: {"coins": 150})
    r = _buy(client, token, item.id)
    assert r.status_code == 200
    assert r.json()["effect"] == {"coins": 150, "mystery_box": 1}
    assert r.json()["balance"] == 230
    monkeypatch.setattr(shop, "roll_mystery_box", lambda rng=None: {"hearts": 5})
    again = _buy(client, token, item.id)  # cùng key → kết quả cũ, không trừ thêm
    assert again.json() == r.json()
    profile.refresh_from_db()
    assert profile.coins == 230
    reasons = list(CoinTransaction.objects.filter(user=user).values_list("reason", flat=True))
    assert sorted(reasons) == ["mystery_box", "shop_purchase"]


def test_ruong_tra_hieu_ung_khong_phai_xu(client, token, user, monkeypatch):
    item = _item("mystery_box", 120, {"mystery_box": 1})
    profile = _rich(user)
    profile.hearts = 2
    profile.save()
    monkeypatch.setattr(shop, "roll_mystery_box", lambda rng=None: {"hearts": 5})
    r = _buy(client, token, item.id)
    assert r.json()["effect"] == {"hearts": 3, "mystery_box": 1}


def test_bang_ruong_co_ky_vong_hop_ly():
    total = sum(w for w, _ in shop.MYSTERY_TABLE)
    ev_coins = sum(w * e.get("coins", 0) for w, e in shop.MYSTERY_TABLE) / total
    assert 30 < ev_coins < 120


# --------------------------------------------------------------- hồi sinh streak
def _lose_streak(user, streak=7):
    profile = user.profile
    profile.streak_current = streak
    profile.streak_lost_value = 0
    profile.save()
    from apps.learning.models import DailyActivity

    today = learn.local_today(profile)
    DailyActivity.objects.create(user=user, date=today - timedelta(days=3), xp=10)
    learn.record(profile, xp=5)  # hoạt động đầu tiên hôm nay sau khi bỏ 2 ngày → mất streak
    profile.refresh_from_db()
    return profile


def test_mat_streak_ghi_lai_va_hoi_sinh(client, token, user, api):
    item = _item("streak_repair", 350, {"streak_repair": 1}, category="special")
    profile = _lose_streak(user, 7)
    assert profile.streak_current == 1 and profile.streak_lost_value == 7
    _rich(user)
    wallet = api.get("/shop/wallet", token=token).json()
    assert wallet["streak_repair"]["lost_value"] == 7
    r = _buy(client, token, item.id)
    assert r.status_code == 200 and r.json()["effect"] == {"streak_repair": 7}
    profile.refresh_from_db()
    assert profile.streak_current == 8 and profile.streak_lost_value == 0
    assert api.get("/shop/wallet", token=token).json()["streak_repair"] is None


def test_hoi_sinh_khi_khong_mat_409(client, token, user):
    item = _item("streak_repair", 350, {"streak_repair": 1})
    _rich(user)
    r = _buy(client, token, item.id)
    assert r.status_code == 409 and r.json()["error"]["code"] == "nothing_to_repair"


def test_hoi_sinh_qua_48h_409(client, token, user):
    item = _item("streak_repair", 350, {"streak_repair": 1})
    profile = _rich(user)
    profile.streak_lost_value = 5
    profile.streak_lost_at = djtz.now() - timedelta(hours=49)
    profile.save()
    assert _buy(client, token, item.id).status_code == 409


# --------------------------------------------------------------- premium theo xu
def test_doi_xu_lay_ngay_premium(client, token, user):
    item = _item("premium_day", 1000, {"premium_days": 1}, category="special")
    profile = _rich(user, 2500)
    assert _buy(client, token, item.id, "a").status_code == 200
    assert _buy(client, token, item.id, "b").status_code == 200
    profile.refresh_from_db()
    assert profile.is_premium
    assert timedelta(hours=47) < profile.premium_until - djtz.now() <= timedelta(days=2)


def test_premium_duoc_cong_them_xu(user):
    profile = user.profile
    assert learn.record(profile, coins=10, coin_reason="checkin").coins_earned == 10
    profile.is_premium = True
    profile.premium_until = djtz.now() + timedelta(days=1)
    profile.save()
    assert learn.record(profile, coins=10, coin_reason="checkin").coins_earned == 15


# --------------------------------------------------------------- trang trí
def test_mua_khung_so_huu_trang_bi_thao(client, token, user, api):
    gold = _item(
        "frame_gold",
        500,
        {"cosmetic": 1},
        category="cosmetic",
        meta={"slot": "avatar_frame", "colors": ["#FFE082", "#FF8F00"]},
    )
    neon = _item(
        "frame_neon",
        650,
        {"cosmetic": 1},
        category="cosmetic",
        meta={"slot": "avatar_frame", "colors": ["#FF4DDB"]},
    )
    _rich(user)
    assert _buy(client, token, gold.id, "a").status_code == 200
    r = _buy(client, token, gold.id, "b")
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_owned"
    assert UserCosmetic.objects.filter(user=user, item=gold).exists()

    wallet = api.get("/shop/wallet", token=token).json()
    assert wallet["avatar_frame"] == "frame_gold"  # tự trang bị khung đầu tiên
    assert wallet["avatar_frame_colors"] == ["#FFE082", "#FF8F00"]
    assert wallet["owned_cosmetic_ids"] == [gold.id]

    items = {it["code"]: it for it in api.get("/shop/items", token=token).json()}
    assert items["frame_gold"]["owned"] and items["frame_gold"]["equipped"]
    assert not items["frame_neon"]["owned"]

    r = api.post("/shop/cosmetics/equip", {"item_id": neon.id}, token=token)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_owned"
    r = api.post("/shop/cosmetics/equip", {"item_id": None}, token=token)
    assert r.status_code == 200 and r.json()["avatar_frame"] is None
    me = api.get("/auth/me", token=token).json()["profile"]
    assert me["avatar_frame"] == "" and me["avatar_frame_colors"] == []
    api.post("/shop/cosmetics/equip", {"item_id": gold.id}, token=token)
    me = api.get("/auth/me", token=token).json()["profile"]
    assert me["avatar_frame"] == "frame_gold" and me["avatar_frame_colors"] == [
        "#FFE082",
        "#FF8F00",
    ]


# --------------------------------------------------------------- wishlist
def test_wishlist_bao_khi_du_xu_mot_lan(api, token, user, client):
    item = _item("streak_freeze", 200, {"streak_freeze": 1})
    r = api.post(f"/shop/wishlist/{item.id}", token=token)
    assert r.status_code == 200 and r.json()["wishlist_item_ids"] == [item.id]
    profile = user.profile
    learn.record(profile, coins=100, coin_reason="checkin")
    assert Notification.objects.filter(user=user).count() == 0
    learn.record(profile, coins=100, coin_reason="checkin")
    assert Notification.objects.filter(user=user).count() == 1
    assert Notification.objects.get(user=user).data == {"screen": "shop", "item_id": item.id}
    learn.record(profile, coins=100, coin_reason="checkin")
    assert Notification.objects.filter(user=user).count() == 1  # chỉ báo 1 lần
    assert api.get("/shop/items", token=token).json()[0]["wishlisted"]
    # mua xong → tự bỏ khỏi wishlist
    _buy(client, token, item.id)
    assert not ShopWishlist.objects.filter(user=user).exists()
    r = api.delete(f"/shop/wishlist/{item.id}", token=token)
    assert r.status_code == 200 and r.json()["wishlisted"] is False


# --------------------------------------------------------------- ví + kiếm xu
def test_wallet_mac_dinh(api, token, user):
    w = api.get("/shop/wallet", token=token).json()
    assert w["coins"] == 0 and w["hearts_max"] == 5 and w["xp_boost_active"] is False
    assert w["streak_repair"] is None and w["premium_coin_bonus_pct"] == 50


def test_earn_goi_y(api, token, user):
    Challenge.objects.create(
        code="daily_xp",
        scope="daily",
        metric="xp",
        title_vi="Kiếm XP",
        description_vi="d",
        target=30,
        reward_xp=20,
        reward_coins=10,
    )
    Game.objects.create(code="word_rain", title_vi="Mưa từ vựng", description_vi="d", kind="reflex")
    codes = [o["code"] for o in api.get("/shop/earn", token=token).json()]
    assert codes == ["checkin", "challenge:daily_xp", "game:word_rain", "premium"]
    api.post("/learn/checkin", token=token)
    out = api.get("/shop/earn", token=token).json()
    assert out[0]["done"] is True


# --------------------------------------------------------------- gói xu (billing)
def test_products_loc_theo_kind(api, token):
    Product.objects.create(
        code="premium_year", name_vi="Năm", period="year", price=1, kind="premium"
    )
    Product.objects.create(
        code="coins_500", name_vi="500 xu", period="one_time", price=19000, kind="coins", coins=500
    )
    assert [p["code"] for p in api.get("/billing/products?kind=coins", token=token).json()] == [
        "coins_500"
    ]
    assert len(api.get("/billing/products", token=token).json()) == 2


def test_webhook_goi_xu_cong_xu_idempotent(user):
    Product.objects.create(
        code="coins_500", name_vi="500 xu", period="one_time", price=19000, kind="coins", coins=500
    )
    for _ in range(2):
        process_payment_event(
            provider="payos",
            event_id="payos:e1",
            event_type="purchase",
            user=user,
            product_code="coins_500",
            expires_at=None,
            payload={},
        )
    user.profile.refresh_from_db()
    assert user.profile.coins == 500 and not user.profile.is_premium
    tx = CoinTransaction.objects.get(user=user)
    assert tx.reason == "coin_pack" and tx.ref_id == "payos:e1"


def test_transactions_kem_ten_vat_pham(api, token, user, client):
    item = _item("streak_freeze", 200, {"streak_freeze": 1})
    item.title_vi = "Băng bảo vệ streak"
    item.save()
    _rich(user, 500)
    _buy(client, token, item.id)
    body = api.get("/coins/transactions", token=token).json()
    assert body["items"][0]["label_vi"] == "Băng bảo vệ streak"
    assert body["items"][0]["amount"] == -200
