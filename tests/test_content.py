"""21 endpoint nội dung (G2): auth, premium gating, accent, phân trang, bước học."""

import pytest

from apps.content.models import (
    Collocation,
    GrammarExample,
    GrammarPoint,
    IPASound,
    Lesson,
    LessonStep,
    Level,
    PhrasalVerb,
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
    assert body["collocations"][0]["text_en"] == "beautiful day"
    assert body["examples"][0]["text_en"] == "A beautiful voice."
    assert len(body["syllables"]) == 3 and body["syllables"][0]["is_primary"] is True
    assert body["audio_us_url"].endswith("audio/us/beautiful.mp3")


def test_vocab_detail_404(api, token, levels):
    assert api.get("/content/vocabulary/999999", token=token).status_code == 404


def test_topics_word_count(api, token, levels, vocab):
    t = Topic.objects.create(code="travel", name_vi="Du lịch", name_en="Travel")
    vocab.topics.add(t)
    body = api.get("/content/topics", token=token).json()
    assert body[0]["word_count"] == 1


# --------------------------------------------------------------- ngữ pháp
def test_grammar_list_va_detail(api, token, levels):
    a1, _ = levels
    gp = GrammarPoint.objects.create(
        level=a1,
        order=1,
        category="Thì",
        title_vi="to be",
        formula="I + am",
        explanation_vi="Động từ to be",
        conjugation=[{"subject": "I", "form": "am"}],
    )
    GrammarExample.objects.create(
        grammar_point=gp, order=0, text_en="I am a student.", text_vi="Tôi là học sinh."
    )
    assert api.get("/content/grammar?level=A1", token=token).json()["count"] == 1
    body = api.get(f"/content/grammar/{gp.id}", token=token).json()
    assert body["conjugation"][0] == {"subject": "I", "form": "am"}
    assert body["examples"][0]["text_en"] == "I am a student."


def test_grammar_a2_premium(api, token, levels):
    _, a2 = levels
    gp = GrammarPoint.objects.create(level=a2, order=1, title_vi="X", explanation_vi="Y")
    assert api.get(f"/content/grammar/{gp.id}", token=token).status_code == 403


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
        deck=dk, order=0, text_en="A red apple.", text_vi="Quả táo đỏ.", ipa="/æ/"
    )
    assert (
        api.get("/content/shadowing?level=A1", token=token).json()["items"][0]["sentence_count"]
        == 1
    )
    body = api.get(f"/content/shadowing/{dk.id}", token=token).json()
    assert body["sentences"][0]["ipa"] == "/æ/"


# --------------------------------------------------------------- tra cứu
def test_roots_va_phrasal_ipa(api, token, levels, vocab):
    a1, _ = levels
    root = WordRoot.objects.create(
        kind="prefix", text="un-", meaning_vi="không", group_vi="Phủ định"
    )
    root.examples.add(vocab)
    assert api.get("/content/roots?kind=prefix", token=token).json()[0]["example_count"] == 1
    assert (
        api.get(f"/content/roots/{root.id}", token=token).json()["examples"][0]["headword"]
        == "beautiful"
    )

    PhrasalVerb.objects.create(verb_group="get", text="get up", meaning_vi="thức dậy", level=a1)
    assert api.get("/content/phrasal-verbs?verb_group=get", token=token).json()["count"] == 1


def test_ipa_sounds(api, token):
    IPASound.objects.create(
        symbol="iː",
        kind="vowel",
        description_vi="Nguyên âm dài",
        articulation_vi="Môi dẹt",
        sample_words=["sheep"],
    )
    body = api.get("/content/ipa-sounds?kind=vowel", token=token).json()
    assert body[0]["symbol"] == "iː" and body[0]["articulation_vi"] == "Môi dẹt"
