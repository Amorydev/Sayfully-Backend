"""Bậc thầy trọng âm: bốc từ đa âm tiết theo cấp, IPA bỏ dấu nhấn."""

import pytest

from apps.content.models import Level, Vocabulary

pytestmark = pytest.mark.django_db


@pytest.fixture
def token(api, user, password):
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


@pytest.fixture
def a1(db):
    return Level.objects.get_or_create(code="A1", defaults={"name_vi": "Mới bắt đầu", "order": 1})[
        0
    ]


def _word(level, headword, syllables, ipa, stress, meaning="nghĩa", **extra):
    return Vocabulary.objects.create(
        headword=headword,
        pos="n",
        level=level,
        meaning_vi=meaning,
        ipa_us="/x/",
        syllables=syllables,
        ipa_syllables=ipa,
        primary_stress=stress,
        **extra,
    )


@pytest.fixture
def playable(a1):
    return [
        _word(a1, "apple", ["ap", "ple"], ["ˈæp", "əl"], 0),
        _word(a1, "understand", ["un", "der", "stand"], ["ˌʌn", "dər", "ˈstænd"], 2),
        _word(a1, "banana", ["ba", "na", "na"], ["bə", "ˈnæ", "nə"], 1),
        _word(a1, "computer", ["com", "put", "er"], ["kəm", "ˈpjuː", "tər"], 1),
        _word(a1, "beautiful", ["beau", "ti", "ful"], ["ˈbjuː", "tɪ", "fəl"], 0),
    ]


def test_round_bo_tu_khong_choi_duoc(api, token, a1, playable):
    _word(a1, "friend", ["friend"], ["frend"], 0)  # một âm tiết
    _word(a1, "record", ["rec", "ord"], ["ˈrek", "ər", "d"], 0)  # tách lệch nhau
    _word(a1, "bogus", ["bo", "gus"], ["ˈboʊ", "gəs"], 5)  # trọng âm ngoài mảng
    Vocabulary.objects.create(headword="nothing", pos="n", level=a1, meaning_vi="x")  # chưa gen_ipa
    body = api.get("/stress-master/round?level=A1&count=50", token=token).json()
    assert body["level"] == "A1"
    assert sorted(w["headword"] for w in body["words"]) == sorted(w.headword for w in playable)


def test_round_ipa_bo_dau_nhan_va_giu_chi_so(api, token, playable):
    body = api.get("/stress-master/round?level=A1", token=token).json()
    by_word = {w["headword"]: w for w in body["words"]}
    assert by_word["understand"]["ipa_syllables"] == ["ʌn", "dər", "stænd"]
    assert by_word["understand"]["primary_stress"] == 2
    assert by_word["apple"]["syllables"] == ["ap", "ple"]
    assert by_word["apple"]["meaning_vi"] == "nghĩa"
    assert by_word["apple"]["audio_url"] is None


def test_round_count_va_ngau_nhien(api, token, playable):
    body = api.get("/stress-master/round?level=A1&count=5", token=token).json()
    assert len(body["words"]) == 5
    seen = {
        tuple(
            w["headword"]
            for w in api.get("/stress-master/round?level=A1&count=5", token=token).json()["words"]
        )
        for _ in range(6)
    }
    assert len(seen) > 1, "sáu lần bốc phải cho thứ tự khác nhau"
    assert api.get("/stress-master/round?level=A1&count=4", token=token).status_code == 422
    assert api.get("/stress-master/round?level=A1&count=51", token=token).status_code == 422


def test_round_cap_thieu_tu(api, token, a1):
    _word(a1, "apple", ["ap", "ple"], ["ˈæp", "əl"], 0)
    r = api.get("/stress-master/round?level=A1", token=token)
    assert r.status_code == 404


def test_round_cap_khong_hop_le_va_chua_dang_nhap(api, token):
    assert api.get("/stress-master/round?level=Z9", token=token).status_code == 422
    assert api.get("/stress-master/round?level=A1").status_code == 401
