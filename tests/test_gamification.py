"""G6 chunk A: challenges (today/weekly/claim) + badges."""

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
