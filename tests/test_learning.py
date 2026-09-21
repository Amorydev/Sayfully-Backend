"""G4 chunk vòng học: home, path, lesson start/complete/progress, thưởng, streak."""

import pytest
import time_machine

from apps.content.models import (
    IPASound,
    Lesson,
    LessonStep,
    Level,
    Reading,
    ReadingQuestion,
    Topic,
    Unit,
    Vocabulary,
    VocabularyDeck,
    VocabularyDeckCollection,
    VocabularyDeckItem,
)
from apps.gamification.models import Game, GameScore
from apps.learning.models import (
    DailyActivity,
    LessonProgress,
    NotebookEntry,
    ReadingDailyActivity,
    SRSCard,
)

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
    assert body["games"] == []
    assert body["checkin_done"] is False


def test_home_bao_da_diem_danh(api, token, user):
    api.post("/learn/checkin", token=token)
    assert api.get("/home", token=token).json()["checkin_done"] is True


def test_home_tra_cong_cu_hoc_tap_mo_rong(api, token, user, settings):
    settings.AI_ENABLED = False
    NotebookEntry.objects.create(user=user, custom_word="hello", custom_meaning="xin chào")
    IPASound.objects.create(
        symbol="iː",
        kind=IPASound.Kind.VOWEL,
        description_vi="Nguyên âm dài",
    )

    response = api.get("/home", token=token)
    assert response.status_code == 200
    tools = response.json()["learning_tools"]

    assert [tool["code"] for tool in tools] == [
        "ai_tutor",
        "exam_prep",
        "ipa",
        "grammar",
        "roots",
        "video",
        "notebook",
        "dictionary",
        "challenge",
        "hearing",
        "progress",
    ]
    assert tools[0]["action"] == "coming_soon"  # AI_ENABLED=False
    ai = response.json()["ai_tutor"]
    assert ai["enabled"] is False and ai["quota_left"] == 20 and ai["quota_limit"] == 20
    assert tools[2]["title_vi"] == "Bảng 1 âm IPA chuẩn"
    assert tools[2]["item_count"] == 1
    assert tools[3]["action"] == "grammar"
    assert tools[4]["action"] == "roots" and tools[4]["item_count"] == 0
    assert tools[5]["action"] == "video"
    assert tools[6]["description_vi"] == "1 từ đã lưu từ các bài đọc"
    assert tools[6]["item_count"] == 1
    assert tools[6]["action"] == "notebook"
    assert tools[7]["action"] == "dictionary"


def test_practice_hub_da_xoa(api, token):
    assert api.get("/learn/practice-hub", token=token).status_code == 404


def test_home_tra_game_theo_level_va_ky_luc_ca_nhan(api, token, user, levels):
    Game.objects.create(
        code="word_rain",
        title_vi="Mưa từ vựng",
        description_vi="Hứng từ đúng",
        kind="reflex",
        min_level="A1",
        is_featured=True,
        order=1,
    )
    locked = Game.objects.create(
        code="speed_type",
        title_vi="Gõ nhanh",
        description_vi="Gõ từ thật nhanh",
        kind="reflex",
        min_level="A2",
        order=2,
    )
    GameScore.objects.create(user=user, game=locked, level="A1", score=420)

    games = api.get("/home", token=token).json()["games"]
    assert games[0]["code"] == "word_rain" and games[0]["is_locked"] is False
    assert games[1]["code"] == "speed_type"
    assert games[1]["is_locked"] is True and games[1]["personal_best"] == 420


# --------------------------------------------------------------- path + khoá
def test_path_liet_ke_va_khoa(api, token, unit):
    _lesson_with_vocab(unit, 1, "a1-u1-l1")
    _lesson_with_vocab(unit, 2, "a1-u1-l2")
    body = api.get("/learn/path?level=A1", token=token).json()
    u = body["units"][0]
    assert u["lesson_count"] == 2 and u["done_count"] == 0
    assert u["lessons"][0]["is_locked"] is False
    assert u["lessons"][1]["is_locked"] is True  # bài 2 khoá tới khi xong bài 1


def test_path_tra_unit_sheet_server_driven(api, token, user, unit):
    unit.reward = {"coins": 150, "badge_code": "unit1_master"}
    unit.save(update_fields=["reward"])
    first = Lesson.objects.create(
        unit=unit,
        order=1,
        code="a1-u1-l1",
        title_vi="Hello & goodbye",
        title_en="Hello & goodbye",
        path_subtitle_vi="Khởi động phát âm tự nhiên",
        est_minutes=8,
        xp_reward=20,
    )
    current = Lesson.objects.create(
        unit=unit,
        order=2,
        code="a1-u1-l2",
        title_vi="Giới thiệu bản thân",
        title_en="Introducing yourself",
        path_subtitle_vi="Đại từ & câu chào hỏi cơ bản",
        est_minutes=10,
        xp_reward=20,
    )
    Lesson.objects.create(
        unit=unit,
        order=3,
        code="a1-u1-l3",
        title_vi="Hỏi thăm",
        title_en="Asking how someone is",
        path_subtitle_vi="Hỏi thăm và phản hồi tự nhiên",
        est_minutes=12,
        xp_reward=20,
    )
    LessonProgress.objects.create(
        user=user,
        lesson=first,
        status=LessonProgress.Status.COMPLETED,
        xp_earned=20,
        stars=3,
    )
    LessonProgress.objects.create(
        user=user,
        lesson=current,
        status=LessonProgress.Status.IN_PROGRESS,
        xp_earned=0,
    )

    body = api.get("/learn/path?level=A1", token=token).json()
    path_unit = body["units"][0]
    rows = path_unit["lessons"]

    assert path_unit["sheet"] == {
        "progress_percent": 33,
        "xp_total": 60,
        "cta": {"lesson_code": current.code, "label_vi": "Tiếp tục Bài 2", "enabled": True},
    }
    assert rows[0]["display_title_vi"] == "Bài 1 · Hello & goodbye"
    assert rows[0]["subtitle_vi"] == "Khởi động phát âm tự nhiên"
    assert rows[0]["state_label_vi"] == "Hoàn thành"
    assert rows[1]["state_label_vi"] == "Đang học" and rows[1]["is_primary"] is True
    assert rows[2]["is_locked"] is True
    assert rows[2]["unlock_hint_vi"] == "Mở khóa sau Bài 2"
    assert rows[2]["completion_reward"] == {
        "label_vi": "Cột mốc nhận thưởng",
        "reward_coins": 150,
        "badge_code": "unit1_master",
        "is_reached": False,
    }
    assert sum(row["is_primary"] for row in rows) == 1


def test_path_sheet_unit_khoa_tra_cta_disabled(api, token, unit, levels):
    _lesson_with_vocab(unit, 1, "a1-u1-l1")
    a1, _ = levels
    locked_unit = Unit.objects.create(
        level=a1,
        order=2,
        code="a1-u2",
        title_vi="Gia đình",
        title_en="Family",
    )
    Lesson.objects.create(
        unit=locked_unit,
        order=1,
        code="a1-u2-l1",
        title_vi="Thành viên gia đình",
        title_en="Family members",
        path_subtitle_vi="Từ vựng về gia đình",
    )

    body = api.get("/learn/path?level=A1", token=token).json()
    path_unit = body["units"][1]

    assert path_unit["is_locked"] is True
    assert path_unit["sheet"]["cta"] == {
        "lesson_code": None,
        "label_vi": "Hoàn thành chặng 1 để mở",
        "enabled": False,
    }
    assert path_unit["lessons"][0]["unlock_hint_vi"] == "Hoàn thành chặng 1 để mở"


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


# --------------------------------------------------------------- SRS review
def _due_card(user, level, hw="apple"):
    from django.utils import timezone as djtz

    from apps.content.models import Vocabulary
    from apps.learning.models import SRSCard

    v = Vocabulary.objects.create(
        headword=hw,
        pos="n",
        level=level,
        meaning_vi="táo",
        ipa_us="/æ/",
        ipa_syllables=["æ"],
        primary_stress=0,
    )
    return SRSCard.objects.create(user=user, vocabulary=v, due_at=djtz.now())


def test_review_due_liet_ke(api, token, user, levels):
    a1, _ = levels
    _due_card(user, a1)
    body = api.get("/learn/review/due", token=token).json()
    assert len(body) == 1 and body[0]["headword"] == "apple"


def test_review_cap_nhat_va_xp(api, token, user, levels):
    from django.utils import timezone as djtz

    from apps.learning.models import SRSReviewLog

    a1, _ = levels
    card = _due_card(user, a1)
    body = api.post(
        "/learn/review", [{"vocab_id": card.vocabulary_id, "rating": 3}], token=token
    ).json()
    assert body["reviewed"] == 1 and body["xp_earned"] == 2
    card.refresh_from_db()
    assert card.reps == 1 and card.due_at > djtz.now()  # dời lịch tương lai
    assert SRSReviewLog.objects.filter(user=user).count() == 1
    assert api.get("/learn/review/due", token=token).json() == []  # hết đến hạn


def test_review_rating_sai_422(api, token, user, levels):
    a1, _ = levels
    card = _due_card(user, a1)
    r = api.post("/learn/review", [{"vocab_id": card.vocabulary_id, "rating": 9}], token=token)
    assert r.status_code == 422


def test_review_stats(api, token, user, levels):
    a1, _ = levels
    card = _due_card(user, a1)
    api.post("/learn/review", [{"vocab_id": card.vocabulary_id, "rating": 3}], token=token)
    body = api.get("/learn/review/stats", token=token).json()
    assert body["studied"] == 1 and body["reviewed_today"] == 1
    assert body["retention_percent"] == 100


# --------------------------------------------------------------- vocab status + notebook
def test_vocab_status(api, token, user, levels):
    from django.utils import timezone as djtz

    from apps.content.models import Topic, Vocabulary
    from apps.learning.models import SRSCard

    a1, _ = levels
    a1.word_target = 10
    a1.save()
    t = Topic.objects.create(code="travel", name_vi="Du lịch", name_en="Travel")
    v1 = Vocabulary.objects.create(headword="a", pos="n", level=a1, meaning_vi="x")
    v2 = Vocabulary.objects.create(headword="b", pos="n", level=a1, meaning_vi="y")
    v1.topics.add(t)
    v2.topics.add(t)
    SRSCard.objects.create(user=user, vocabulary=v1, due_at=djtz.now(), state=2)  # đã vững
    SRSCard.objects.create(
        user=user, vocabulary=v2, due_at=djtz.now(), state=1
    )  # đang học, đến hạn
    api.post("/learn/notebook", {"vocab_id": v1.id, "tags": ["IELTS"]}, token=token)

    body = api.get("/learn/vocabulary/status?level=A1", token=token).json()
    assert body["summary"] == {
        "total": 10,
        "studied": 2,
        "mastered": 1,
        "learning": 1,
        "due_today": 2,
        "percent": 20,
    }
    assert v1.id in body["learned_ids"] and v1.id in body["fav_ids"]
    assert v2.id in body["due_ids"]
    assert body["notebook"] == {"total": 1, "categories": 1}
    assert body["topics"][0] == {"id": t.id, "done": 2, "total": 2}


def test_notebook_add_list_delete(api, token, user, levels):
    from apps.content.models import Vocabulary

    a1, _ = levels
    v = Vocabulary.objects.create(
        headword="apple", pos="n", level=a1, meaning_vi="táo", ipa_us="/æ/"
    )
    r = api.post(
        "/learn/notebook", {"vocab_id": v.id, "note": "hay", "tags": ["IELTS"]}, token=token
    )
    eid = r.json()["id"]
    assert r.json()["headword"] == "apple" and r.json()["tags"] == ["IELTS"]
    notebook = api.get("/learn/notebook", token=token).json()
    assert notebook["count"] == 1
    assert notebook["notebook_total"] == 1
    assert notebook["capacity"] == 100
    assert notebook["is_premium"] is False
    assert notebook["tag_facets"] == [{"tag": "IELTS", "count": 1}]
    assert notebook["items"][0]["mastery_percent"] == 0
    assert notebook["items"][0]["reps"] == 0
    assert notebook["items"][0]["lapses"] == 0
    assert notebook["items"][0]["due_at"] is None
    assert api.get("/learn/notebook?tag=IELTS", token=token).json()["count"] == 1
    assert api.get("/learn/notebook?tag=XXX", token=token).json()["count"] == 0
    assert api.delete(f"/learn/notebook/{eid}", token=token).status_code == 204
    assert api.delete(f"/learn/notebook/{eid}", token=token).status_code == 404


def test_notebook_duplicate_updates(api, token, user, levels):
    from apps.content.models import Vocabulary
    from apps.learning.models import NotebookEntry

    a1, _ = levels
    v = Vocabulary.objects.create(headword="apple", pos="n", level=a1, meaning_vi="táo")
    api.post("/learn/notebook", {"vocab_id": v.id, "note": "one"}, token=token)
    api.post("/learn/notebook", {"vocab_id": v.id, "note": "two"}, token=token)
    assert NotebookEntry.objects.filter(user=user).count() == 1
    assert NotebookEntry.objects.get(user=user).note == "two"


def test_notebook_limit_403(api, token, user, levels, monkeypatch):
    from apps.content.models import Vocabulary
    from apps.learning import api as lapi

    monkeypatch.setattr(lapi, "NOTEBOOK_LIMITS", {False: 1, True: 1})
    a1, _ = levels
    v1 = Vocabulary.objects.create(headword="a", pos="n", level=a1, meaning_vi="x")
    v2 = Vocabulary.objects.create(headword="b", pos="n", level=a1, meaning_vi="y")
    api.post("/learn/notebook", {"vocab_id": v1.id}, token=token)
    r = api.post("/learn/notebook", {"vocab_id": v2.id}, token=token)
    assert r.status_code == 403 and r.json()["error"]["code"] == "notebook_limit"


# --------------------------------------------------------------- checkin / activity / practice / skills
def test_checkin_idempotent(api, token, user, levels):
    r1 = api.post("/learn/checkin", token=token).json()
    assert r1["already"] is False and r1["xp_earned"] == 5 and r1["coins_earned"] == 10
    assert r1["streak_days"] == 1 and len(r1["week"]) == 7
    assert r1["streak_before"] == 0 and r1["milestone"] is None
    r2 = api.post("/learn/checkin", token=token).json()
    assert r2["already"] is True and r2["xp_earned"] == 0
    assert r2["streak_before"] == 1 and r2["streak_days"] == 1
    user.profile.refresh_from_db()
    assert user.profile.coins == 10 and user.profile.xp_total == 5  # không cộng đôi


def test_checkin_dung_bang_giu_chuoi(api, token, user, levels):
    """Lỡ hôm qua + còn băng: /home báo at_risk, điểm danh tiêu 1 băng, chuỗi tiếp tục,
    ngày hôm qua được đánh dấu frozen trên dải tuần."""
    from datetime import timedelta

    from apps.learning.models import DailyActivity
    from apps.learning.services import local_today

    profile = user.profile
    today = local_today(profile)
    DailyActivity.objects.create(user=user, date=today - timedelta(days=2), xp=10)
    profile.streak_current = 5
    profile.streak_freezes = 1
    profile.save(update_fields=["streak_current", "streak_freezes"])

    home = api.get("/home", token=token).json()["streak"]
    assert home == {"days": 5, "freezes": 1, "at_risk": True, "frozen_yesterday": False}

    r = api.post("/learn/checkin", token=token).json()
    assert r["streak_before"] == 5 and r["streak_days"] == 6
    assert r["freeze_used"] is True and r["freezes_left"] == 0
    frozen = [d for d in r["week"] if d["frozen"]]
    # hôm qua có thể rơi vào tuần trước (thứ Hai) → khi đó dải tuần không có ngày đóng băng
    assert len(frozen) == (0 if today.weekday() == 0 else 1)

    home = api.get("/home", token=token).json()["streak"]
    assert home["at_risk"] is False and home["frozen_yesterday"] is True


def test_checkin_het_bang_mat_chuoi(api, token, user, levels):
    from datetime import timedelta

    from apps.learning.models import DailyActivity
    from apps.learning.services import local_today

    profile = user.profile
    DailyActivity.objects.create(user=user, date=local_today(profile) - timedelta(days=2), xp=10)
    profile.streak_current = 5
    profile.save(update_fields=["streak_current"])

    r = api.post("/learn/checkin", token=token).json()
    assert r["streak_before"] == 5 and r["streak_days"] == 1 and r["freeze_used"] is False


def test_activity_range(api, token, user, levels):
    from datetime import date, timedelta

    from apps.learning.models import DailyActivity

    today = date(2026, 3, 10)
    DailyActivity.objects.create(user=user, date=today, xp=50, words_reviewed=10)
    DailyActivity.objects.create(user=user, date=today - timedelta(days=1), xp=20)
    body = api.get("/learn/activity?from=2026-03-01&to=2026-03-31", token=token).json()
    assert len(body) == 2 and body[-1]["date"] == "2026-03-10" and body[-1]["xp"] == 50


def test_practice_xp_va_skill(api, token, user, levels):
    from apps.learning.models import UserSkill

    body = api.post(
        "/learn/practice", {"kind": "speaking", "score": 80, "duration_sec": 60}, token=token
    ).json()
    assert body["xp_earned"] == 8 and body["skill"] == "speaking" and body["skill_level"] == 1
    assert UserSkill.objects.get(user=user, kind="speaking").xp == 8
    user.profile.refresh_from_db()
    assert user.profile.xp_total == 8


def test_practice_kind_sai_422(api, token, user, levels):
    r = api.post("/learn/practice", {"kind": "dancing", "score": 50}, token=token)
    assert r.status_code == 422


def test_skills_overview_va_goi_y(api, token, user, levels):
    api.post("/learn/practice", {"kind": "speaking", "score": 100}, token=token)
    body = api.get("/learn/skills", token=token).json()
    assert len(body["skills"]) == 4
    kinds = {sk["kind"] for sk in body["skills"]}
    assert kinds == {"speaking", "listening", "reading", "writing"}
    assert body["suggestion"]["kind"] != "speaking"  # gợi ý kỹ năng yếu nhất, không phải nói


# --------------------------------------------------------------- reading list + progress (C10a)
def test_reading_list_progress_facets_and_premium_lock(api, token, user, levels):
    a1, a2 = levels
    life = Topic.objects.create(code="life", name_vi="Đời sống", name_en="Life", order=1)
    travel = Topic.objects.create(
        code="travel", name_vi="Du lịch", name_en="Travel", order=2, icon_url="icons/travel.png"
    )
    vocabulary = Vocabulary.objects.create(headword="family", pos="n", level=a1, meaning_vi="gia đình")
    reading = Reading.objects.create(
        level=a1,
        order=1,
        title_en="My family",
        title_vi="Gia đình tôi",
        topic=life,
        est_minutes=2,
    )
    reading.keywords.add(vocabulary)
    ReadingQuestion.objects.create(
        reading=reading, order=1, question_en="Who?", options=["A", "B"], answer_index=0
    )
    ReadingQuestion.objects.create(
        reading=reading, order=2, question_en="Where?", options=["A", "B"], answer_index=1
    )
    Reading.objects.create(
        level=a1, order=2, title_en="First flight", title_vi="Chuyến bay", topic=travel
    )
    premium_reading = Reading.objects.create(
        level=a2, order=1, title_en="Advanced", title_vi="Nâng cao"
    )

    body = api.get("/learn/readings", token=token).json()
    assert body["overview"]["level"] == "A1"
    assert body["overview"]["total"] == 2
    assert body["topic_facets"] == [
        {"topic_id": life.id, "name_vi": "Đời sống", "count": 1},
        {"topic_id": travel.id, "name_vi": "Du lịch", "count": 1},
    ]
    first = body["items"][0]
    assert first["keyword_preview"] == ["family"]
    assert first["progress"]["status"] == "not_started"
    assert first["topic_icon_url"] is None  # topic chưa có icon → app hiện placeholder
    assert body["items"][1]["topic_icon_url"].endswith("/icons/travel.png")

    partial = api.post(
        f"/learn/readings/{reading.id}/progress",
        {"answered_count": 1, "correct_count": 1, "duration_sec": 60},
        token=token,
    ).json()
    assert partial["progress"]["status"] == "in_progress"
    assert partial["progress"]["progress_percent"] == 50
    assert partial["xp_awarded"] == 0

    completed = api.post(
        f"/learn/readings/{reading.id}/progress",
        {"answered_count": 2, "correct_count": 2, "completed": True, "duration_sec": 120},
        token=token,
    ).json()
    assert completed["progress"]["status"] == "completed"
    assert completed["progress"]["score_percent"] == 100
    assert completed["xp_awarded"] == 20
    assert ReadingDailyActivity.objects.filter(user=user).count() == 1

    duplicate = api.post(
        f"/learn/readings/{reading.id}/progress",
        {"answered_count": 2, "correct_count": 2, "completed": True},
        token=token,
    ).json()
    assert duplicate["xp_awarded"] == 0
    assert duplicate["progress"]["status"] == "completed"

    locked = api.get("/learn/readings?level=A2", token=token).json()["items"]
    assert locked[0]["id"] == premium_reading.id
    assert locked[0]["is_locked"] is True


def test_reading_progress_rejects_invalid_answer_counts(api, token, levels):
    a1, _ = levels
    reading = Reading.objects.create(level=a1, order=1, title_en="A", title_vi="B")
    ReadingQuestion.objects.create(
        reading=reading, order=1, question_en="Q", options=["A", "B"], answer_index=0
    )
    response = api.post(
        f"/learn/readings/{reading.id}/progress",
        {"answered_count": 1, "correct_count": 2},
        token=token,
    )
    assert response.status_code == 422
    premature_complete = api.post(
        f"/learn/readings/{reading.id}/progress",
        {"answered_count": 0, "correct_count": 0, "completed": True},
        token=token,
    )
    assert premature_complete.status_code == 422


# --------------------------------------------------------------- preferences / avatar
def test_preferences_partial_update(api, token, user):
    body = api.patch(
        "/me/preferences",
        {"accent": "UK", "daily_goal_words": 20, "reminder_time": "07:30", "full_name": "Quyền"},
        token=token,
    ).json()
    assert body["accent"] == "UK" and body["daily_goal_words"] == 20
    assert body["reminder_time"] == "07:30" and body["full_name"] == "Quyền"
    user.profile.refresh_from_db()
    assert user.profile.accent == "UK" and user.profile.daily_goal_words == 20


def test_preferences_accent_sai_422(api, token, user):
    assert api.patch("/me/preferences", {"accent": "XX"}, token=token).status_code == 422


def test_preferences_reminder_time_sai_422(api, token, user):
    r = api.patch("/me/preferences", {"reminder_time": "25h"}, token=token)
    assert r.status_code == 422


def test_avatar_upload(client, token, user, monkeypatch):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.learning import api as lapi

    monkeypatch.setattr(lapi, "upload_avatar", lambda key, data, ct: key)
    f = SimpleUploadedFile("a.png", b"imgdata", content_type="image/png")
    r = client.post(
        "/api/v1/me/avatar", {"file": f}, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    assert r.json()["avatar_url"].endswith(f"avatars/{user.id}.png")
    user.refresh_from_db()
    assert user.avatar_path == f"avatars/{user.id}.png"


def test_avatar_type_sai_415(client, token, monkeypatch):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.learning import api as lapi

    monkeypatch.setattr(lapi, "upload_avatar", lambda key, data, ct: key)
    f = SimpleUploadedFile("a.gif", b"x", content_type="image/gif")
    r = client.post(
        "/api/v1/me/avatar", {"file": f}, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 415


# --------------------------------------------------------------- placement
def _placement_qs(a1):
    from apps.learning.models import PlacementQuestion

    for i in range(3):
        PlacementQuestion.objects.create(
            order=i + 1, skill="vocab", level="A1", prompt_en=f"Q{i}",
            options=["a", "b"], answer_index=0,
        )
    for i in range(3):
        PlacementQuestion.objects.create(
            order=i + 4, skill="grammar", level="A2", prompt_en=f"G{i}",
            options=["a", "b"], answer_index=1,
        )


def test_placement_questions_khong_lo_dap_an(api, token, levels):
    a1, _ = levels
    _placement_qs(a1)
    body = api.get("/placement/questions", token=token).json()
    assert len(body) == 6
    assert "answer_index" not in body[0]  # không lộ đáp án


def test_placement_submit_cham_va_de_xuat(api, token, user, levels):
    from apps.content.models import Unit
    from apps.learning.models import PlacementQuestion

    a1, a2 = levels
    Unit.objects.create(level=a2, order=1, code="a2-u1", title_vi="U", title_en="U")
    _placement_qs(a1)
    qs = list(PlacementQuestion.objects.order_by("order"))
    # trả lời đúng hết A1 (answer 0) và A2 (answer 1) -> đề xuất A2
    answers = [{"question_id": q.id, "answer": q.answer_index} for q in qs]
    body = api.post("/placement/submit", answers, token=token).json()
    assert body["suggested_level"] == "A2"
    assert body["start_unit_code"] == "a2-u1"
    skills = {s["skill"]: s for s in body["skill_scores"]}
    assert skills["vocab"]["correct"] == 3 and skills["grammar"]["correct"] == 3
    user.profile.refresh_from_db()
    assert user.profile.cefr_level == "A2"


# --------------------------------------------------------------- thư viện bộ thẻ (C7a → C7)
@pytest.fixture
def decks(levels):
    a1, a2 = levels
    popular = VocabularyDeckCollection.objects.create(
        code="popular", title_vi="Bộ sưu tập phổ biến", chip_label_vi="Thông dụng", order=1
    )
    oxford = VocabularyDeckCollection.objects.create(
        code="oxford", title_vi="Từ vựng Oxford", chip_label_vi="Oxford", order=2
    )
    free = VocabularyDeck.objects.create(
        collection=popular, code="oxford-3000", title_vi="3000 từ Oxford thông dụng",
        cover_title="Oxford 3000", badge_vi="A1 – B2",
        background_url="images/decks/oxford-3000.png", level=a1, order=1,
        is_free=True, learner_base=354_000,
    )
    pro = VocabularyDeck.objects.create(
        collection=oxford, code="ielts-75", title_vi="IELTS Speaking & Writing 7.5+",
        cover_title="IELTS Advance", badge_vi="Band 7.5+",
        background_url="https://cdn.example/ielts.png", level=a2, order=1,
        is_free=False, learner_base=198_000,
    )
    for i in range(3):
        v = Vocabulary.objects.create(
            headword=f"deckword{i}", pos="n", level=a1, meaning_vi="nghĩa",
            ipa_us=f"/us{i}/", ipa_uk=f"/uk{i}/",
        )
        VocabularyDeckItem.objects.create(deck=free, vocabulary=v, order=i)
    return free, pro


def test_flashcard_decks_groups_by_collection_with_counts(api, token, decks):
    free, pro = decks
    body = api.get("/learn/flashcard/decks", token=token).json()

    assert [c["code"] for c in body["collections"]] == ["popular", "oxford"]
    assert body["continuing"] is None  # chưa mở bộ nào

    popular = body["collections"][0]
    assert popular["deck_count"] == 1
    card = popular["decks"][0]
    assert card["card_count"] == 3
    assert card["learner_count"] == 354_000  # learner_base, chưa ai mở bộ
    assert card["is_premium"] is False
    assert card["cover_title"] == "Oxford 3000"
    assert card["background_url"].endswith("images/decks/oxford-3000.png")
    assert card["learned_count"] == 0

    locked = body["collections"][1]["decks"][0]
    assert locked["is_premium"] is True
    assert locked["background_url"] == "https://cdn.example/ielts.png"  # URL đầy đủ giữ nguyên


def test_flashcard_deck_detail_returns_all_cards_and_marks_continuing(api, token, decks):
    free, _ = decks
    body = api.get(f"/learn/flashcard/decks/{free.id}", token=token).json()

    assert body["total"] == 3
    assert len(body["cards"]) == 3
    first = body["cards"][0]
    assert first["headword"] == "deckword0"
    assert first["ipa"] == "/us0/"  # accent mặc định US
    assert first["state"] == 0 and first["due_at"] is None  # chưa ôn bao giờ
    assert body["learned_count"] == 0

    # mở bộ xong thì bộ đó thành "Đang học" và được tính là 1 học viên
    listing = api.get("/learn/flashcard/decks", token=token).json()
    assert listing["continuing"]["id"] == free.id
    assert listing["collections"][0]["decks"][0]["learner_count"] == 354_001


def test_flashcard_deck_detail_locked_for_free_user(api, token, decks):
    _, pro = decks
    response = api.get(f"/learn/flashcard/decks/{pro.id}", token=token)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "premium_required"


def test_flashcard_deck_detail_404(api, token, decks):
    assert api.get("/learn/flashcard/decks/999999", token=token).status_code == 404
