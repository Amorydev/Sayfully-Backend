"""E2E smoke — vòng học xuyên app (G11 gia cố): auth → content → learn → review → home."""

import pytest

from apps.content.models import Lesson, LessonStep, Level, Unit, Vocabulary

pytestmark = pytest.mark.django_db


def test_full_learning_loop(api):
    # 1. đăng ký
    reg = api.post(
        "/auth/register",
        {"email": "e2e@example.com", "password": "MatKhauRatManh123", "full_name": "E2E"},
    )
    assert reg.status_code == 200
    token = reg.json()["access"]

    # 2. seed nội dung A1
    a1 = Level.objects.create(code="A1", name_vi="Sơ cấp", order=1, is_free=True)
    unit = Unit.objects.create(level=a1, order=1, code="a1-u1", title_vi="U", title_en="U")
    lesson = Lesson.objects.create(unit=unit, order=1, code="a1-u1-l1", title_vi="B", title_en="L")
    v = Vocabulary.objects.create(headword="apple", pos="n", level=a1, meaning_vi="táo", ipa_us="/æ/")
    LessonStep.objects.create(lesson=lesson, order=1, kind="vocab", vocabulary=v)
    LessonStep.objects.create(
        lesson=lesson, order=2, kind="quiz",
        payload={"prompt_vi": "?", "options": ["a"], "correct_index": 0},
    )

    # 3. đọc nội dung (G2)
    assert "A1" in [lv["code"] for lv in api.get("/content/levels", token=token).json()]
    ld = api.get("/content/lessons/a1-u1-l1", token=token).json()
    assert ld["new_word_count"] == 1 and len(ld["steps"]) == 2

    # 4. bắt đầu + hoàn thành bài (G4)
    assert api.post("/learn/lessons/a1-u1-l1/start", token=token).json()["status"] == "in_progress"
    res = api.post(
        "/learn/lessons/a1-u1-l1/complete", {"correct_count": 10, "total": 10}, token=token
    ).json()
    assert res["stars"] == 3 and res["xp_earned"] == 50 and res["srs_cards_created"] == 1

    # 5. ôn tập SRS (G4)
    due = api.get("/learn/review/due", token=token).json()
    assert len(due) == 1 and due[0]["headword"] == "apple"
    assert api.post("/learn/review", [{"vocab_id": v.id, "rating": 3}], token=token).json()["reviewed"] == 1

    # 6. điểm danh (G4)
    assert api.post("/learn/checkin", token=token).json()["already"] is False

    # 7. trang chủ phản ánh toàn bộ (G4 tổng hợp)
    home = api.get("/home", token=token).json()
    assert home["profile"]["xp"] > 0 and home["profile"]["streak_days"] >= 1
    assert home["profile"]["coins"] > 0  # xu từ complete + checkin

    # 8. billing mặc định free (G7)
    assert api.get("/billing/subscription", token=token).json()["is_premium"] is False
