"""21 endpoint nội dung (G2): auth, premium gating, accent, phân trang, bước học."""

import pytest

from apps.content.models import (
    Collocation,
    GrammarPoint,
    Lesson,
    LessonStep,
    Level,
    Reading,
    ReadingSentence,
    ShadowingDeck,
    ShadowingSentence,
    Story,
    StoryScene,
    StorySentence,
    Topic,
    Unit,
    Vocabulary,
    VocabularyExample,
    WordRoot,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def token(api, user, password) -> str:
    r = api.post("/auth/token", {"email": user.email, "password": password})
    return r.json()["access"]


@pytest.fixture
def levels():
    a1 = Level.objects.create(code="A1", name_vi="Sơ cấp", order=1, word_target=600, is_free=True)
    a2 = Level.objects.create(
        code="A2", name_vi="Sơ trung", order=2, word_target=800, is_free=False
    )
    return a1, a2


@pytest.fixture
def vocab(levels):
    a1, _ = levels
    v = Vocabulary.objects.create(
        headword="beautiful",
        pos="adj",
        level=a1,
        meaning_vi="đẹp",
        ipa_uk="/ˈbjuːtɪfl/",
        ipa_us="/ˈbjuːtɪfəl/",
        ipa_syllables=["bjuː", "tɪ", "fəl"],
        primary_stress=0,
        audio_uk_path="audio/uk/beautiful.mp3",
        audio_us_path="audio/us/beautiful.mp3",
        frequency_rank=100,
        synonyms=["lovely", "gorgeous"],
        antonyms=["ugly"],
        definition_vi="Đẹp hoặc làm người khác cảm thấy dễ chịu.",
    )
    VocabularyExample.objects.create(
        vocabulary=v, order=0, text_en="A beautiful voice.", text_vi="Một giọng hát đẹp."
    )
    Collocation.objects.create(vocabulary=v, text_en="beautiful day", meaning_vi="ngày đẹp")
    return v


# --------------------------------------------------------------- auth
def test_khong_token_bi_401(api, levels):
    assert api.get("/content/levels").status_code == 401


def test_levels_tra_du(api, token, levels):
    r = api.get("/content/levels", token=token)
    assert r.status_code == 200, r.content
    body = r.json()
    assert [x["code"] for x in body] == ["A1", "A2"]
    assert body[0]["is_free"] is True and body[1]["is_free"] is False


# --------------------------------------------------------------- lộ trình
def test_units_va_lesson_count(api, token, levels):
    a1, _ = levels
    unit = Unit.objects.create(
        level=a1, order=1, code="a1-u1", title_vi="Chào hỏi", title_en="Greetings"
    )
    Lesson.objects.create(unit=unit, order=1, code="a1-u1-l1", title_vi="Bài 1", title_en="L1")
    r = api.get("/content/levels/A1/units", token=token)
    assert r.status_code == 200
    assert r.json()[0]["lesson_count"] == 1


def test_units_level_khong_ton_tai_404(api, token, levels):
    assert api.get("/content/levels/Z9/units", token=token).status_code == 404


def test_unit_detail_kem_bai(api, token, levels):
    a1, _ = levels
    unit = Unit.objects.create(
        level=a1, order=1, code="a1-u1", title_vi="U", title_en="U", reward={"coins": 150}
    )
    Lesson.objects.create(unit=unit, order=1, code="a1-u1-l1", title_vi="B1", title_en="L1")
    r = api.get(f"/content/units/{unit.id}", token=token)
    body = r.json()
    assert body["reward"] == {"coins": 150}
    assert len(body["lessons"]) == 1 and body["lessons"][0]["code"] == "a1-u1-l1"


# --------------------------------------------------------------- lesson detail + bước
def _make_lesson(level, vocab, code="a1-u1-l1"):
    unit = Unit.objects.create(
        level=level, order=1, code=f"{level.code.lower()}-u1", title_vi="U", title_en="U"
    )
    lesson = Lesson.objects.create(unit=unit, order=1, code=code, title_vi="Bài", title_en="Lesson")
    LessonStep.objects.create(
        lesson=lesson,
        order=1,
        kind="intro",
        payload={"highlight_vi": "Chào hỏi", "preview": [{"text_en": "Hi", "text_vi": "Chào"}]},
    )
    LessonStep.objects.create(lesson=lesson, order=2, kind="vocab", vocabulary=vocab)
    LessonStep.objects.create(
        lesson=lesson,
        order=3,
        kind="quiz",
        payload={
            "prompt_vi": "Chọn nghĩa",
            "question_word": "beautiful",
            "options": ["đẹp", "xấu"],
            "correct_index": 0,
            "xp": 10,
        },
    )
    return lesson


def test_lesson_detail_buoc_da_hinh(api, token, levels, vocab):
    a1, _ = levels
    _make_lesson(a1, vocab)
    r = api.get("/content/lessons/a1-u1-l1", token=token)
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["new_word_count"] == 1
    kinds = [s["kind"] for s in body["steps"]]
    assert kinds == ["intro", "vocab", "quiz"]
    quiz = body["steps"][2]["quiz"]
    assert quiz["correct_index"] == 0 and quiz["options"][0]["text"] == "đẹp"
    assert body["steps"][1]["vocab"]["headword"] == "beautiful"


def test_lesson_a2_khoa_voi_free_user(api, token, levels, vocab):
    _, a2 = levels
    _make_lesson(a2, vocab, code="a2-u1-l1")
    r = api.get("/content/lessons/a2-u1-l1", token=token)
    assert r.status_code == 403 and r.json()["error"]["code"] == "premium_required"


def test_lesson_a2_mo_voi_premium(api, token, user, levels, vocab):
    _, a2 = levels
    _make_lesson(a2, vocab, code="a2-u1-l1")
    api.get("/content/levels", token=token)  # ensure_profile
    user.profile.is_premium = True
    user.profile.save()
    assert api.get("/content/lessons/a2-u1-l1", token=token).status_code == 200


def test_lesson_khong_ton_tai_404(api, token, levels):
    assert api.get("/content/lessons/khong-co", token=token).status_code == 404


# --------------------------------------------------------------- từ vựng
def test_vocab_list_loc_va_phan_trang(api, token, levels, vocab):
    r = api.get("/content/vocabulary?level=A1&limit=10", token=token)
    body = r.json()
    assert body["count"] == 1 and body["limit"] == 10
    assert body["items"][0]["headword"] == "beautiful"


def test_vocab_q_tim_theo_nghia(api, token, levels, vocab):
    assert api.get("/content/vocabulary?q=đẹp", token=token).json()["count"] == 1
    assert api.get("/content/vocabulary?q=zzz", token=token).json()["count"] == 0


def test_vocab_search_tra_trang_thai_da_luu(api, token, user, levels, vocab):
    from apps.learning.models import NotebookEntry

    entry = NotebookEntry.objects.create(user=user, vocabulary=vocab)
    item = api.get("/content/vocabulary?q=beautiful", token=token).json()["items"][0]

    assert item["is_saved"] is True
    assert item["notebook_entry_id"] == entry.id


def test_vocab_ipa_theo_accent(api, token, user, levels, vocab):
    api.get("/content/levels", token=token)  # ensure_profile (mặc định US)
    r_us = api.get(f"/content/vocabulary/{vocab.id}", token=token)
    assert r_us.json()["ipa"] == "/ˈbjuːtɪfəl/"
    user.profile.accent = "UK"
    user.profile.save()
    r_uk = api.get(f"/content/vocabulary/{vocab.id}", token=token)
    assert r_uk.json()["ipa"] == "/ˈbjuːtɪfl/"


def test_vocab_detail_du_truong(api, token, levels, vocab):
    body = api.get(f"/content/vocabulary/{vocab.id}", token=token).json()
    assert body["synonyms"] == ["lovely", "gorgeous"]
    assert body["antonyms"] == ["ugly"]
    assert body["definition_vi"] == "Đẹp hoặc làm người khác cảm thấy dễ chịu."
    assert body["collocations"][0]["text_en"] == "beautiful day"
    assert body["examples"][0]["text_en"] == "A beautiful voice."
    assert len(body["syllables"]) == 3 and body["syllables"][0]["is_primary"] is True
    assert body["audio_us_url"].endswith("audio/us/beautiful.mp3")


def test_vocab_detail_tra_metadata_tu_lien_quan_va_trang_thai_luu(api, token, user, levels, vocab):
    from apps.learning.models import NotebookEntry

    related = Vocabulary.objects.create(
        headword="lovely", pos="adj", level=levels[0], meaning_vi="đáng yêu"
    )
    vocab.word_family.add(related)
    entry = NotebookEntry.objects.create(user=user, vocabulary=vocab)

    body = api.get(f"/content/vocabulary/{vocab.id}", token=token).json()

    assert body["is_saved"] is True and body["notebook_entry_id"] == entry.id
    assert body["synonym_items"][0] == {
        "id": related.id,
        "headword": "lovely",
        "pos": "adj",
        "meaning_vi": "đáng yêu",
    }
    assert body["antonym_items"][0]["headword"] == "ugly"
    assert body["word_family_items"][0]["id"] == related.id


def test_vocab_detail_404(api, token, levels):
    assert api.get("/content/vocabulary/999999", token=token).status_code == 404


def test_topics_word_count(api, token, levels, vocab):
    t = Topic.objects.create(code="travel", name_vi="Du lịch", name_en="Travel")
    vocab.topics.add(t)
    body = api.get("/content/topics", token=token).json()
    assert body[0]["word_count"] == 1


# --------------------------------------------------------------- ngữ pháp
def test_grammar_list_va_detail(api, token, levels, user):
    from apps.content.management.commands.seed_grammar import seed_grammar_points

    assert seed_grammar_points() == 8
    page = api.get("/content/grammar?level=A1", token=token).json()
    assert page["count"] == 6 and page["completed"] == 0
    assert page["categories"] == ["Thì", "Mạo từ", "Đại từ", "Câu hỏi", "Cấu trúc"]
    assert page["tip_vi"].startswith("Nắm chắc bản chất")
    first = page["items"][0]
    assert (
        first["title_vi"] == "Động từ to be (am/is/are)"
        and first["subtitle_vi"] == "Khái niệm cốt lõi · 3 quy tắc"
    )
    assert (
        first["exercise_count"] == 8 and first["completed"] is False and first["is_locked"] is False
    )
    assert api.get("/content/grammar?level=A1&category=Mạo từ", token=token).json()["count"] == 1

    body = api.get(f"/content/grammar/{first['id']}", token=token).json()
    assert body["position"] == 1 and body["total_in_level"] == 6
    assert body["formula"] == "S + be + N/Adj"
    assert body["formula_parts"][1] == {"token": "be", "label_vi": "am / is / are"}
    assert (
        body["mistake_wrong"] == "She very beautiful"
        and body["mistake_right"] == "She is very beautiful"
    )
    assert body["conjugation"][0] == {"subject": "I", "form": "am"}
    assert body["examples"][0]["text_en"] == "I am a student." and body["xp_reward"] == 30

    ex = api.get(f"/content/grammar/{first['id']}/exercises", token=token).json()
    assert len(ex) == 8 and ex[0]["options"] == ["am", "is", "are"] and ex[0]["answer_index"] == 0

    r = api.post(
        f"/content/grammar/{first['id']}/practice", {"correct": 5, "total": 10}, token=token
    ).json()
    assert r["percent"] == 50 and r["completed"] is False and r["xp_earned"] == 0
    r = api.post(
        f"/content/grammar/{first['id']}/practice", {"correct": 8, "total": 10}, token=token
    ).json()
    assert r["completed"] is True and r["newly_completed"] is True and r["xp_earned"] == 30
    assert r["streak_days"] == 1
    r = api.post(
        f"/content/grammar/{first['id']}/practice", {"correct": 10, "total": 10}, token=token
    ).json()
    assert r["newly_completed"] is False and r["xp_earned"] == 0 and r["best_percent"] == 100
    user.profile.refresh_from_db()
    assert user.profile.xp_total == 30
    page = api.get("/content/grammar?level=A1", token=token).json()
    assert page["completed"] == 1 and page["items"][0]["completed"] is True
    assert page["tip_vi"] != first["title_vi"] and page["tip_vi"].startswith("Nghe âm đầu")


def test_grammar_a2_premium(api, token, levels):
    _, a2 = levels
    gp = GrammarPoint.objects.create(level=a2, order=1, title_vi="X", explanation_vi="Y")
    assert api.get(f"/content/grammar/{gp.id}", token=token).status_code == 403
    assert api.get(f"/content/grammar/{gp.id}/exercises", token=token).status_code == 403
    assert api.get("/content/grammar?level=A2", token=token).json()["items"][0]["is_locked"] is True


# --------------------------------------------------------------- đọc / truyện
def test_reading_detail_va_premium(api, token, levels, vocab):
    a1, a2 = levels
    r1 = Reading.objects.create(level=a1, order=1, title_en="My family", title_vi="Gia đình")
    ReadingSentence.objects.create(
        reading=r1, order=0, text_en="I have a family.", text_vi="Tôi có gia đình.", ipa="/aɪ/"
    )
    r1.keywords.add(vocab)
    body = api.get(f"/content/readings/{r1.id}", token=token).json()
    assert body["sentences"][0]["ipa"] == "/aɪ/"
    assert body["keywords"][0]["headword"] == "beautiful"
    assert body["keywords"][0]["level"] == "A1"
    assert body["keywords"][0]["audio_url"].endswith("audio/us/beautiful.mp3")
    assert body["topic"] is None and body["cover_url"] is None

    r2 = Reading.objects.create(level=a2, order=1, title_en="X", title_vi="Y")
    assert api.get(f"/content/readings/{r2.id}", token=token).status_code == 403


def test_story_detail(api, token, levels):
    a1, _ = levels
    st = Story.objects.create(level=a1, order=1, title_en="Apple", title_vi="Táo", genre="daily")
    sc = StoryScene.objects.create(story=st, order=0)
    StorySentence.objects.create(
        scene=sc, order=0, text_en="Tom has an apple.", text_vi="Tom có quả táo."
    )
    body = api.get(f"/content/stories/{st.id}", token=token).json()
    assert body["scenes"][0]["sentences"][0]["text_en"] == "Tom has an apple."


# --------------------------------------------------------------- shadowing / video
def test_shadowing_list_detail(api, token, levels):
    a1, _ = levels
    dk = ShadowingDeck.objects.create(level=a1, order=1, title_en="Apple", focus_vi="Âm /æ/")
    ShadowingSentence.objects.create(
        deck=dk,
        order=0,
        text_en="A red apple.",
        text_vi="Quả táo đỏ.",
        ipa="/æ/",
        speaking_goal_vi="Nhấn rõ âm /æ/",
        highlights=[{"text": "apple", "kind": "primary_stress"}],
    )
    assert (
        api.get("/content/shadowing?level=A1", token=token).json()["items"][0]["sentence_count"]
        == 1
    )
    body = api.get(f"/content/shadowing/{dk.id}", token=token).json()
    assert body["sentences"][0]["ipa"] == "/æ/"
    assert body["sentences"][0]["speaking_goal_vi"] == "Nhấn rõ âm /æ/"
    assert body["sentences"][0]["highlights"] == [{"text": "apple", "kind": "primary_stress"}]


# --------------------------------------------------------------- tra cứu
def test_roots_va_phrasal_ipa(api, token, levels, vocab):
    from apps.content.management.commands.seed_roots import seed_word_roots

    assert seed_word_roots() == 40
    un = WordRoot.objects.get(kind="prefix", text="un-")
    un.examples.add(vocab)  # "beautiful" liên kết tay → id có, split không tách được

    board = api.get("/content/roots", token=token).json()  # mặc định prefix
    assert board["total"] == 40 and board["learned"] == 0 and board["kind_total"] == 14
    assert [g["title_vi"] for g in board["groups"]] == [
        "Phủ định & Đối nghịch",
        "Vị trí & Thời gian",
        "Số lượng & Mức độ",
    ]
    first = board["groups"][0]["roots"][0]
    assert first["text"] == "un-" and first["example_count"] == 6 and first["learned"] is False
    assert api.get("/content/roots?kind=suffix", token=token).json()["kind_total"] == 12

    detail = api.get(f"/content/roots/{un.id}", token=token).json()
    assert detail["effect_vi"] == "Biến đổi nghĩa sang đối lập tức thì"
    assert (
        detail["examples"][0]["headword"] == "beautiful" and detail["examples"][0]["id"] == vocab.id
    )
    unhappy = detail["examples"][1]
    assert unhappy == {
        "id": None,
        "headword": "unhappy",
        "base": "happy",
        "split": "un·happy",
        "ipa": "/ʌnˈhæp.i/",
        "meaning_vi": "không vui vẻ",
    }
    assert len(detail["distractors"]) >= 4 and "không vui vẻ" not in detail["distractors"]

    r = api.post(
        f"/content/roots/{un.id}/practice", {"correct": 5, "total": 10}, token=token
    ).json()
    assert r["percent"] == 50 and r["learned"] is False and r["total_learned"] == 0
    r = api.post(
        f"/content/roots/{un.id}/practice", {"correct": 8, "total": 10}, token=token
    ).json()
    assert r["learned"] is True and r["newly_learned"] is True and r["total_learned"] == 1
    r = api.post(
        f"/content/roots/{un.id}/practice", {"correct": 2, "total": 10}, token=token
    ).json()
    assert r["best_percent"] == 80 and r["newly_learned"] is False and r["attempts"] == 3
    board = api.get("/content/roots", token=token).json()
    assert board["learned"] == 1 and board["groups"][0]["roots"][0]["learned"] is True
    assert api.get("/content/roots/999999", token=token).status_code == 404


def test_ipa_sounds(api, token):
    from apps.content.management.commands.seed_ipa import seed_ipa_sounds

    assert seed_ipa_sounds() == 44
    body = api.get("/content/ipa-sounds", token=token).json()
    assert body["total"] == 44 and body["mastered"] == 0
    assert [g["code"] for g in body["groups"]] == [
        "monophthong",
        "diphthong",
        "voiceless",
        "voiced",
        "nasal_approx",
    ]
    assert sum(len(g["sounds"]) for g in body["groups"]) == 44
    first = body["groups"][0]["sounds"][0]
    assert (
        first["symbol"] == "iː" and first["sample_word"] == "sheep" and first["mastered"] is False
    )

    vowels = api.get("/content/ipa-sounds?kind=vowel", token=token).json()
    assert [g["code"] for g in vowels["groups"]] == ["monophthong", "diphthong"]
    assert vowels["total"] == 44  # tổng luôn là cả bảng để tính x/44

    detail = api.get(f"/content/ipa-sounds/{first['id']}", token=token).json()
    assert detail["category_en"] == "Long Vowel" and detail["lips_vi"] == "Bè dẹt"
    assert detail["examples"][0] == {
        "word": "sheep",
        "ipa": "/ʃiːp/",
        "meaning_vi": "con cừu",
        "audio_uk_url": None,
        "audio_us_url": None,
    }
    pair = detail["minimal_pair"]
    assert pair["this"]["word"] == "sheep" and pair["other"]["symbol"] == "ɪ"
    assert pair["other"]["category_vi"] == "Nguyên âm ngắn" and pair["other"]["id"]

    # luyện: 60 chưa thuần thục, 85 → thuần thục, gọi lại không tính lại
    r = api.post(f"/content/ipa-sounds/{first['id']}/practice", {"score": 60}, token=token).json()
    assert r["mastered"] is False and r["attempts"] == 1 and r["total_mastered"] == 0
    r = api.post(f"/content/ipa-sounds/{first['id']}/practice", {"score": 85}, token=token).json()
    assert r["mastered"] is True and r["newly_mastered"] is True and r["total_mastered"] == 1
    r = api.post(f"/content/ipa-sounds/{first['id']}/practice", {"score": 50}, token=token).json()
    assert r["best_score"] == 85 and r["newly_mastered"] is False and r["attempts"] == 3

    body = api.get("/content/ipa-sounds", token=token).json()
    assert body["mastered"] == 1 and body["groups"][0]["sounds"][0]["mastered"] is True
    assert api.get("/content/ipa-sounds/999999", token=token).status_code == 404
