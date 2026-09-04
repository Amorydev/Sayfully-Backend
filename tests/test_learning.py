"""G4 chunk vòng học: home, path, lesson start/complete/progress, thưởng, streak."""

import pytest
import time_machine

from apps.content.models import Lesson, LessonStep, Level, Unit, Vocabulary
from apps.learning.models import DailyActivity, LessonProgress, SRSCard

pytestmark = pytest.mark.django_db


@pytest.fixture
def token(api, user, password) -> str:
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


@pytest.fixture
def levels():
    a1 = Level.objects.create(code="A1", name_vi="Sơ cấp", order=1, is_free=True)
    a2 = Level.objects.create(code="A2", name_vi="Sơ trung", order=2, is_free=False)
    return a1, a2


@pytest.fixture
def unit(levels):
    a1, _ = levels
    return Unit.objects.create(
        level=a1, order=1, code="a1-u1", title_vi="Chào hỏi", title_en="Greet"
    )


def _lesson_with_vocab(unit, order, code, n_vocab=2, xp=50):
    lesson = Lesson.objects.create(
        unit=unit, order=order, code=code, title_vi=f"Bài {order}", title_en="L", xp_reward=xp
    )
    for i in range(n_vocab):
        v = Vocabulary.objects.create(
            headword=f"word{order}_{i}", pos="n", level=unit.level, meaning_vi="x"
        )
        LessonStep.objects.create(lesson=lesson, order=i + 1, kind="vocab", vocabulary=v)
    return lesson


# --------------------------------------------------------------- home
def test_home_mac_dinh(api, token, user):
    body = api.get("/home", token=token).json()
    assert body["profile"]["cefr_level"] == "A1"
    assert body["profile"]["hearts"] == 5
    assert body["due_review_count"] == 0
    assert body["current_lesson"] is None
    assert body["daily_goal"]["words_target"] == 10


# --------------------------------------------------------------- path + khoá
def test_path_liet_ke_va_khoa(api, token, unit):
    _lesson_with_vocab(unit, 1, "a1-u1-l1")
    _lesson_with_vocab(unit, 2, "a1-u1-l2")
    body = api.get("/learn/path?level=A1", token=token).json()
    u = body["units"][0]
    assert u["lesson_count"] == 2 and u["done_count"] == 0
    assert u["lessons"][0]["is_locked"] is False
    assert u["lessons"][1]["is_locked"] is True  # bài 2 khoá tới khi xong bài 1


def test_path_level_khong_ton_tai_404(api, token, levels):
    assert api.get("/learn/path?level=Z9", token=token).status_code == 404


# --------------------------------------------------------------- start
def test_start_tao_progress(api, token, unit):
    _lesson_with_vocab(unit, 1, "a1-u1-l1")
    r = api.post("/learn/lessons/a1-u1-l1/start", token=token)
    assert r.status_code == 200 and r.json()["status"] == "in_progress"


def test_start_bai_khoa_403(api, token, unit):
    _lesson_with_vocab(unit, 1, "a1-u1-l1")
    _lesson_with_vocab(unit, 2, "a1-u1-l2")
    r = api.post("/learn/lessons/a1-u1-l2/start", token=token)
    assert r.status_code == 403 and r.json()["error"]["code"] == "lesson_locked"


def test_start_a2_premium(api, token, levels):
    _, a2 = levels
    u2 = Unit.objects.create(level=a2, order=1, code="a2-u1", title_vi="U", title_en="U")
    _lesson_with_vocab(u2, 1, "a2-u1-l1")
    r = api.post("/learn/lessons/a2-u1-l1/start", token=token)
    assert r.status_code == 403 and r.json()["error"]["code"] == "premium_required"


# --------------------------------------------------------------- complete
def test_complete_thuong_va_tao_srs(api, token, user, unit):
    _lesson_with_vocab(unit, 1, "a1-u1-l1", n_vocab=2, xp=50)
    r = api.post(
        "/learn/lessons/a1-u1-l1/complete",
        {"correct_count": 10, "total": 10, "duration_sec": 120},
        token=token,
    )
    body = r.json()
    assert body["stars"] == 3 and body["xp_earned"] == 50 and body["coins_earned"] == 5
    assert body["streak_days"] == 1 and body["srs_cards_created"] == 2
    user.profile.refresh_from_db()
    assert user.profile.xp_total == 50 and user.profile.coins == 5
    assert SRSCard.objects.filter(user=user).count() == 2
    assert LessonProgress.objects.get(user=user).status == "completed"


def test_complete_idempotent_khong_cong_doi(api, token, user, unit):
    _lesson_with_vocab(unit, 1, "a1-u1-l1", xp=50)
    api.post("/learn/lessons/a1-u1-l1/complete", {"correct_count": 8, "total": 10}, token=token)
    r2 = api.post(
        "/learn/lessons/a1-u1-l1/complete", {"correct_count": 8, "total": 10}, token=token
    )
    assert r2.json()["xp_earned"] == 0  # lần 2 không thưởng
    user.profile.refresh_from_db()
    assert user.profile.xp_total == 50  # không cộng đôi
    assert SRSCard.objects.filter(user=user).count() == 2  # không tạo trùng


def test_complete_mo_khoa_bai_ke(api, token, unit):
    _lesson_with_vocab(unit, 1, "a1-u1-l1")
    _lesson_with_vocab(unit, 2, "a1-u1-l2")
    api.post("/learn/lessons/a1-u1-l1/complete", {"correct_count": 10, "total": 10}, token=token)
    assert api.post("/learn/lessons/a1-u1-l2/start", token=token).status_code == 200


def test_complete_sao_theo_ty_le(api, token, unit):
    _lesson_with_vocab(unit, 1, "a1-u1-l1")
    body = api.post(
        "/learn/lessons/a1-u1-l1/complete", {"correct_count": 5, "total": 10}, token=token
    ).json()
    assert body["stars"] == 1  # 50% -> 1 sao


# --------------------------------------------------------------- progress
def test_progress_mac_dinh_not_started(api, token, unit):
    _lesson_with_vocab(unit, 1, "a1-u1-l1")
    assert (
        api.get("/learn/lessons/a1-u1-l1/progress", token=token).json()["status"] == "not_started"
    )


# --------------------------------------------------------------- streak
def test_streak_tang_qua_ngay(api, user, password, unit):
    _lesson_with_vocab(unit, 1, "a1-u1-l1")
    _lesson_with_vocab(unit, 2, "a1-u1-l2")
    login = {"email": user.email, "password": password}
    with time_machine.travel("2026-03-10 08:00 +0000", tick=False):
        tok = api.post("/auth/token", login).json()["access"]
        b1 = api.post(
            "/learn/lessons/a1-u1-l1/complete", {"correct_count": 10, "total": 10}, token=tok
        ).json()
        assert b1["streak_days"] == 1
    with time_machine.travel("2026-03-11 08:00 +0000", tick=False):
        tok = api.post("/auth/token", login).json()["access"]
        b2 = api.post(
            "/learn/lessons/a1-u1-l2/complete", {"correct_count": 10, "total": 10}, token=tok
        ).json()
        assert b2["streak_days"] == 2 and b2["is_streak_record"] is True
    assert DailyActivity.objects.filter(user=user).count() == 2
