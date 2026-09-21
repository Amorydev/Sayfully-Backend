from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.content.models import Level, Video, VideoSubtitle
from apps.content.video_transcript import (
    CaptionCue,
    parse_caption_text,
    segment_cues,
    sentence_to_ipa,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def video():
    level = Level.objects.create(code="A1", name_vi="Sơ cấp", order=1, is_free=True)
    return Video.objects.create(
        level=level,
        youtube_id="video_123",
        title_en="A day outside",
        title_vi="Một ngày bên ngoài",
        duration_sec=30,
    )


def test_parse_vtt_bo_nhac_va_doc_timestamp():
    content = """WEBVTT

00:00:00.000 --> 00:00:01.000
[Music]

00:00:01.200 --> 00:00:03.400 align:start
<c>Hello &amp; welcome</c>
"""
    assert parse_caption_text(content) == [CaptionCue(1200, 3400, "Hello & welcome")]


def test_segment_cues_gom_fragment_thanh_cau_va_tach_khoang_lang():
    cues = [
        CaptionCue(1000, 2200, "Welcome to"),
        CaptionCue(2200, 3600, "our class."),
        CaptionCue(5200, 6500, "Let us begin!"),
    ]
    drafts = segment_cues(cues)
    assert [(row.start_ms, row.end_ms, row.text_en) for row in drafts] == [
        (1000, 3600, "Welcome to our class."),
        (5200, 6500, "Let us begin!"),
    ]


def test_sentence_to_ipa_la_tat_dinh_va_bao_tu_thieu():
    dictionary = {"hello": [["HH", "AH0", "L", "OW1"]]}
    ipa, missing = sentence_to_ipa("Hello Kiki!", dictionary)
    assert ipa == "/hə.ˈloʊ/"
    assert missing == ["Kiki"]


def test_command_import_json_sinh_ipa_va_giu_ban_dich(video, tmp_path):
    source = tmp_path / "subtitles.json"
    source.write_text(
        """[
          {"start_ms": 1000, "end_ms": 2500, "text_en": "Hello.", "text_vi": "Xin chào."},
          {"start_ms": 3000, "end_ms": 5000, "text_en": "Welcome home.", "text_vi": "Mừng bạn về nhà."}
        ]""",
        encoding="utf-8",
    )
    out = StringIO()
    call_command("import_video_subtitles", source, "--video-id", video.id, stdout=out)
    rows = list(video.subtitles.order_by("order"))
    assert [row.order for row in rows] == [1, 2]
    assert rows[0].ipa.startswith("/") and rows[0].text_vi == "Xin chào."
    assert "Đã xử lý 2 câu" in out.getvalue()


def test_command_khong_ghi_de_neu_thieu_force(video, tmp_path):
    VideoSubtitle.objects.create(
        video=video,
        order=1,
        start_ms=0,
        end_ms=1000,
        text_en="Existing.",
        text_vi="Đang có.",
    )
    source = tmp_path / "subtitles.json"
    source.write_text(
        '[{"start_ms": 1000, "end_ms": 2000, "text_en": "New."}]',
        encoding="utf-8",
    )
    with pytest.raises(CommandError, match="--force"):
        call_command("import_video_subtitles", source, "--video-id", video.id)
    assert video.subtitles.get().text_en == "Existing."


def test_command_translate_va_thay_the_atomically(video, tmp_path, monkeypatch):
    VideoSubtitle.objects.create(
        video=video, order=1, start_ms=0, end_ms=1000, text_en="Old.", text_vi="Cũ."
    )
    source = tmp_path / "subtitles.srt"
    source.write_text(
        """1
00:00:01,000 --> 00:00:02,500
Hello there.
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "apps.content.video_transcript.translate_texts_to_vi",
        lambda texts: ["Xin chào."] if texts == ["Hello there."] else [],
    )
    call_command(
        "import_video_subtitles",
        source,
        "--youtube-id",
        video.youtube_id,
        "--translate",
        "--force",
    )
    row = video.subtitles.get()
    assert (row.start_ms, row.end_ms, row.text_en, row.text_vi) == (
        1000,
        2500,
        "Hello there.",
        "Xin chào.",
    )


def test_command_dry_run_khong_thay_database(video, tmp_path):
    source = tmp_path / "subtitles.json"
    source.write_text(
        '[{"start_ms": 1000, "end_ms": 2000, "text_en": "Hello."}]',
        encoding="utf-8",
    )
    call_command(
        "import_video_subtitles",
        source,
        "--video-id",
        video.id,
        "--dry-run",
    )
    assert video.subtitles.count() == 0


def test_video_endpoint_tra_transcript_da_import(api, user, password, video):
    VideoSubtitle.objects.create(
        video=video,
        order=1,
        start_ms=1200,
        end_ms=3400,
        text_en="Hello there.",
        ipa="/hə.ˈloʊ ðɛr/",
        text_vi="Xin chào.",
    )
    token = api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]
    body = api.get(f"/content/videos/{video.id}", token=token).json()
    assert body["subtitles"] == [
        {
            "order": 1,
            "start_ms": 1200,
            "end_ms": 3400,
            "text_en": "Hello there.",
            "ipa": "/hə.ˈloʊ ðɛr/",
            "text_vi": "Xin chào.",
        }
    ]


def test_content_audit_bao_video_thieu_transcript(video):
    out = StringIO()
    call_command("content_audit", "--level", "A1", stdout=out)
    assert "Video thiếu transcript" in out.getvalue()
