"""G3 pipeline: import_vocab, gen_ipa, gen_audio, content_audit + phonemics."""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.content.management.commands import gen_audio
from apps.content.models import Level, Vocabulary
from apps.content.phonemics import arpabet_to_ipa

pytestmark = pytest.mark.django_db


@pytest.fixture
def a1():
    return Level.objects.create(code="A1", name_vi="Sơ cấp", order=1, is_free=True)


# --------------------------------------------------------------- phonemics (unit)
def test_arpabet_to_ipa_stress_va_am_tiet():
    p = arpabet_to_ipa(["B", "Y", "UW1", "T", "AH0", "F", "AH0", "L"])
    assert p.ipa == "/ˈbjuː.tə.fəl/"
    assert p.ipa_syllables == ["ˈbjuː", "tə", "fəl"]
    assert p.primary_stress == 0 and p.secondary_stress is None


def test_arpabet_secondary_stress():
    p = arpabet_to_ipa(["AH2", "N", "D", "ER0", "S", "T", "AE1", "N", "D"])
    assert p.primary_stress == 2 and p.secondary_stress == 0


# --------------------------------------------------------------- L1 import_vocab
CSV = (
    "headword,pos,level,meaning_vi,synonyms,examples,collocations\n"
    'apple,n,A1,quả táo,fruit,I eat an apple.|Tôi ăn táo.;;An apple a day.|Mỗi ngày một quả.,'
    "red apple|táo đỏ\n"
)


def test_import_vocab_va_idempotent(a1, tmp_path):
    f = tmp_path / "vocab.csv"
    f.write_text(CSV, encoding="utf-8")

    call_command("import_vocab", str(f), stdout=StringIO())
    v = Vocabulary.objects.get(headword="apple", pos="n")
    assert v.meaning_vi == "quả táo" and v.synonyms == ["fruit"]
    assert v.examples.count() == 2 and v.collocations.count() == 1

    call_command("import_vocab", str(f), stdout=StringIO())  # chạy lại
    assert Vocabulary.objects.filter(headword="apple").count() == 1
    assert Vocabulary.objects.get(headword="apple", pos="n").examples.count() == 2


def test_import_vocab_dry_run_khong_ghi(a1, tmp_path):
    f = tmp_path / "vocab.csv"
    f.write_text(CSV, encoding="utf-8")
    call_command("import_vocab", str(f), "--dry-run", stdout=StringIO())
    assert Vocabulary.objects.count() == 0


def test_import_vocab_bo_dong_thieu_truong(a1, tmp_path):
    f = tmp_path / "bad.csv"
    f.write_text("headword,pos,level,meaning_vi\napple,n,A1,\n", encoding="utf-8")
    call_command("import_vocab", str(f), stdout=StringIO(), stderr=StringIO())
    assert Vocabulary.objects.count() == 0


# --------------------------------------------------------------- L2 gen_ipa
def test_gen_ipa_tu_cmudict(a1):
    v = Vocabulary.objects.create(headword="apple", pos="n", level=a1, meaning_vi="táo")
    call_command("gen_ipa", "--level", "A1", stdout=StringIO())
    v.refresh_from_db()
    assert v.ipa_us.startswith("/") and "æ" in v.ipa_us
    assert v.primary_stress == 0
    assert v.syllables == ["ap", "ple"]  # pyphen
    assert len(v.ipa_syllables) == 2


def test_gen_ipa_idempotent_bo_qua_da_co(a1):
    v = Vocabulary.objects.create(
        headword="apple", pos="n", level=a1, meaning_vi="táo", ipa_us="/CU/"
    )
    call_command("gen_ipa", "--level", "A1", stdout=StringIO())
    v.refresh_from_db()
    assert v.ipa_us == "/CU/"  # không đụng


def test_gen_ipa_force_ghi_de(a1):
    v = Vocabulary.objects.create(
        headword="apple", pos="n", level=a1, meaning_vi="táo", ipa_us="/CU/"
    )
    call_command("gen_ipa", "--level", "A1", "--force", stdout=StringIO())
    v.refresh_from_db()
    assert v.ipa_us != "/CU/" and "æ" in v.ipa_us


# --------------------------------------------------------------- L3 gen_audio
@pytest.fixture
def fake_tts(monkeypatch):
    calls = []
    monkeypatch.setattr(gen_audio, "synthesize", lambda text, accent: b"MP3DATA")
    monkeypatch.setattr(gen_audio, "upload_r2", lambda key, data: calls.append(key) or key)
    return calls


def test_gen_audio_upload_va_ghi_path(a1, fake_tts):
    v = Vocabulary.objects.create(headword="apple", pos="n", level=a1, meaning_vi="táo")
    call_command("gen_audio", "--level", "A1", "--accent", "US", stdout=StringIO())
    v.refresh_from_db()
    assert v.audio_us_path == "audio/us/apple.mp3"
    assert fake_tts == ["audio/us/apple.mp3"]


def test_gen_audio_idempotent(a1, fake_tts):
    Vocabulary.objects.create(
        headword="apple", pos="n", level=a1, meaning_vi="táo", audio_us_path="audio/us/apple.mp3"
    )
    call_command("gen_audio", "--level", "A1", "--accent", "US", stdout=StringIO())
    assert fake_tts == []  # đã có audio -> không gọi TTS


def test_gen_audio_dry_run(a1, fake_tts):
    v = Vocabulary.objects.create(headword="apple", pos="n", level=a1, meaning_vi="táo")
    call_command("gen_audio", "--level", "A1", "--accent", "US", "--dry-run", stdout=StringIO())
    v.refresh_from_db()
    assert v.audio_us_path == "" and fake_tts == []


def test_gen_audio_limit(a1, fake_tts):
    for w in ["apple", "banana", "cherry"]:
        Vocabulary.objects.create(headword=w, pos="n", level=a1, meaning_vi="x")
    call_command("gen_audio", "--level", "A1", "--accent", "US", "--limit", "2", stdout=StringIO())
    assert len(fake_tts) == 2


# --------------------------------------------------------------- L4 content_audit
def test_content_audit_bao_thieu(a1):
    Vocabulary.objects.create(headword="apple", pos="n", level=a1, meaning_vi="táo")
    out = StringIO()
    call_command("content_audit", "--level", "A1", stdout=out)
    text = out.getvalue()
    assert "Thiếu IPA" in text and "Thiếu audio US" in text
