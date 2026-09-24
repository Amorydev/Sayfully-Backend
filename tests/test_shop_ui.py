"""C50 Cửa hàng: chỉ bán vật phẩm có hiệu ứng, chặn bơm tim khi tim đầy, /auth/me trả số băng."""

import json

import pytest

from apps.gamification.models import ShopItem

pytestmark = pytest.mark.django_db


@pytest.fixture
def token(api, user, password):
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


def _item(code, cost, effect):
    return ShopItem.objects.create(
        code=code, title_vi=code, description_vi="x", cost_coins=cost, effect=effect
    )


def _purchase(client, token, item_id, key="k1"):
    return client.post(
        "/api/v1/shop/purchase",
        data=json.dumps({"item_id": item_id}),
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
    )


def test_shop_items_an_vat_pham_chua_cai_hieu_ung(api, token):
    _item("refill_hearts", 150, {"hearts": 5})
    _item("streak_freeze", 200, {"streak_freeze": 1})
    _item("magic_hat", 120, {"magic_hat": 1})
    codes = [it["code"] for it in api.get("/shop/items", token=token).json()]
    assert codes == ["refill_hearts", "streak_freeze"]


def test_mua_bom_tim_khi_tim_day_409(client, token, user):
    item = _item("refill_hearts", 150, {"hearts": 5})
    user.profile.coins = 500
    user.profile.hearts = 5
    user.profile.save()
    r = _purchase(client, token, item.id)
    assert r.status_code == 409 and r.json()["error"]["code"] == "hearts_full"
    user.profile.refresh_from_db()
    assert user.profile.coins == 500


def test_mua_vat_pham_chua_cai_hieu_ung_404(client, token, user):
    item = _item("magic_hat", 120, {"magic_hat": 1})
    user.profile.coins = 500
    user.profile.save()
    assert _purchase(client, token, item.id).status_code == 404


def test_me_tra_so_bang_streak(api, token, client, user):
    item = _item("streak_freeze", 200, {"streak_freeze": 1})
    user.profile.coins = 500
    user.profile.save()
    _purchase(client, token, item.id)
    body = api.get("/auth/me", token=token).json()
    assert body["profile"]["streak_freezes"] == 1
    assert body["profile"]["coins"] == 300
