"""G6 chunk A: challenges (today/weekly/claim) + badges."""

import json

import pytest

from apps.gamification.models import Badge, Challenge, UserChallenge
from apps.learning.models import DailyActivity
from apps.learning.services import local_today

pytestmark = pytest.mark.django_db


@pytest.fixture
def token(api, user, password):
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


def _daily_challenge(target=30, metric="xp"):
    return Challenge.objects.create(
        code="daily_xp", scope="daily", metric=metric, title_vi="Kiếm XP",
        description_vi="Đạt mục tiêu XP", target=target, reward_xp=20, reward_coins=10,
    )


def _activity_today(user, **kw):
    today = local_today(user.profile)
    return DailyActivity.objects.create(user=user, date=today, **kw)


# --------------------------------------------------------------- challenges
def test_challenges_today_tien_do(api, token, user):
    _daily_challenge(target=30)
    _activity_today(user, xp=30)
    body = api.get("/challenges/today", token=token).json()
    assert body[0]["current"] == 30 and body[0]["target"] == 30
    assert body[0]["completed"] is True and body[0]["claimed"] is False


def test_challenges_today_chua_du(api, token, user):
    _daily_challenge(target=50)
    _activity_today(user, xp=20)
    body = api.get("/challenges/today", token=token).json()
    assert body[0]["current"] == 20 and body[0]["completed"] is False


def test_claim_thuong(api, token, user):
    ch = _daily_challenge(target=30)
    _activity_today(user, xp=30)
    body = api.post(f"/challenges/{ch.id}/claim", token=token).json()
    assert body["xp_earned"] == 20 and body["coins_earned"] == 10
    user.profile.refresh_from_db()
    assert user.profile.coins == 10 and user.profile.xp_total == 20
    assert UserChallenge.objects.get(user=user).claimed_at is not None


def test_claim_lan_hai_409(api, token, user):
    ch = _daily_challenge(target=30)
    _activity_today(user, xp=30)
    api.post(f"/challenges/{ch.id}/claim", token=token)
    r = api.post(f"/challenges/{ch.id}/claim", token=token)
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_claimed"


def test_claim_chua_hoan_thanh_409(api, token, user):
    ch = _daily_challenge(target=50)
    _activity_today(user, xp=10)
    r = api.post(f"/challenges/{ch.id}/claim", token=token)
    assert r.status_code == 409 and r.json()["error"]["code"] == "challenge_incomplete"


def test_claim_khong_ton_tai_404(api, token, user):
    assert api.post("/challenges/999/claim", token=token).status_code == 404


def test_challenges_weekly(api, token, user):
    Challenge.objects.create(code="wk", scope="weekly", metric="lessons", title_vi="Học",
                             description_vi="x", target=5, reward_xp=50, reward_coins=20)
    _activity_today(user, lessons_completed=3)
    body = api.get("/challenges/weekly", token=token).json()
    assert body[0]["current"] == 3 and body[0]["target"] == 5


# --------------------------------------------------------------- badges
def test_badges_mo_khoa_khi_du_dieu_kien(api, token, user):
    Badge.objects.create(code="streak7", title_vi="7 ngày", description_vi="Chuỗi 7 ngày",
                         condition={"metric": "streak", "value": 7}, order=1)
    Badge.objects.create(code="streak30", title_vi="30 ngày", description_vi="Chuỗi 30",
                         condition={"metric": "streak", "value": 30}, order=2)
    user.profile.streak_best = 10
    user.profile.save()
    body = api.get("/badges", token=token).json()
    by_code = {b["code"]: b for b in body}
    assert by_code["streak7"]["unlocked"] is True
    assert by_code["streak30"]["unlocked"] is False


# --------------------------------------------------------------- leaderboard
def _weekly(user, xp=100):
    from apps.gamification.services import current_week
    from apps.learning.models import WeeklyStat

    y, w = current_week()
    return WeeklyStat.objects.create(user=user, iso_year=y, iso_week=w, xp=xp)


def test_leaderboard_league(api, token, user):
    _weekly(user, 100)
    body = api.get("/leaderboard?scope=league", token=token).json()
    assert body["tier"] == "Đồng" and body["my_rank"] == 1
    assert body["entries"][0]["is_me"] is True and body["entries"][0]["xp_week"] == 100
    assert body["promote_top"] == 5 and body["time_left_sec"] > 0


def test_leaderboard_me(api, token, user):
    _weekly(user, 100)
    body = api.get("/leaderboard/me", token=token).json()
    assert body["rank"] == 1 and body["xp_week"] == 100 and body["tier"] == "Đồng"


# --------------------------------------------------------------- shop / coins
def _item(cost=150, effect=None, code="refill_hearts"):
    from apps.gamification.models import ShopItem

    return ShopItem.objects.create(
        code=code, title_vi="Bơm tim", description_vi="x", cost_coins=cost,
        effect=effect or {"hearts": 5},
    )


def _purchase(client, token, item_id, key):
    return client.post(
        "/api/v1/shop/purchase", data=json.dumps({"item_id": item_id}),
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
    )


def test_shop_items(api, token):
    _item()
    body = api.get("/shop/items", token=token).json()
    assert body[0]["code"] == "refill_hearts" and body[0]["cost_coins"] == 150


def test_shop_purchase(client, token, user):
    item = _item(cost=100, effect={"hearts": 5})
    user.profile.coins = 200
    user.profile.hearts = 1
    user.profile.save()
    body = _purchase(client, token, item.id, "key1").json()
    assert body["coins_spent"] == 100 and body["balance"] == 100
    user.profile.refresh_from_db()
    assert user.profile.coins == 100 and user.profile.hearts == 5


def test_shop_purchase_idempotent(client, token, user):
    item = _item(cost=100)
    user.profile.coins = 200
    user.profile.save()
    _purchase(client, token, item.id, "key1")
    _purchase(client, token, item.id, "key1")  # cùng key
    user.profile.refresh_from_db()
    assert user.profile.coins == 100  # chỉ trừ 1 lần


def test_shop_thieu_xu_409(client, token, user):
    item = _item(cost=100)
    user.profile.coins = 50
    user.profile.save()
    r = _purchase(client, token, item.id, "key1")
    assert r.status_code == 409 and r.json()["error"]["code"] == "insufficient_coins"


def test_shop_thieu_idempotency_key_400(api, token, user):
    item = _item(cost=100)
    r = api.post("/shop/purchase", {"item_id": item.id}, token=token)
    assert r.status_code == 400 and r.json()["error"]["code"] == "idempotency_key_missing"


def test_coin_transactions(client, api, token, user):
    item = _item(cost=100)
    user.profile.coins = 200
    user.profile.save()
    _purchase(client, token, item.id, "key1")
    body = api.get("/coins/transactions", token=token).json()
    assert body["count"] == 1 and body["items"][0]["amount"] == -100
