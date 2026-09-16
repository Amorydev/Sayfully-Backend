"""Người dùng Premium dán link YouTube → video học (apps.content.video_import).

YouTube (oEmbed, caption) và LLM đều được mock; import chạy đồng bộ (VIDEO_IMPORT_SYNC).
"""

import pytest

from apps.accounts.services import ensure_profile
from apps.content import video_import
from apps.content.models import Level, UserVideoLibrary, Video
from apps.content.video_transcript import CaptionCue

pytestmark = pytest.mark.django_db

YT = "UF8uR6Z6KLc"
URL = f"https://www.youtube.com/watch?v={YT}"

CUES = [
    CaptionCue(0, 2_000, "Thank you."),
    CaptionCue(2_100, 5_000, "I am honored to be with you today."),
    CaptionCue(5_100, 9_000, "Today I want to tell you three stories from my life."),
]


@pytest.fixture
def token(api, user, password) -> str:
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


@pytest.fixture(autouse=True)
def _setup(settings, monkeypatch):
    settings.AI_PROVIDER = "mock"
    settings.VIDEO_IMPORT_ENABLED = True
    settings.VIDEO_IMPORT_SYNC = True
    settings.VIDEO_IMPORT_MAX_SEC = 1200
    settings.VIDEO_IMPORT_DAILY_LIMIT = 2
    monkeypatch.setattr(
        video_import,
        "fetch_oembed",
        lambda yid: {"title": "Steve Jobs Stanford Speech", "channel": "Stanford"},
    )
    monkeypatch.setattr(video_import, "fetch_captions", lambda yid: list(CUES))
    Level.objects.create(code="B1", name_vi="Trung cấp", order=3, is_free=False)


@pytest.fixture
def premium(user):
    profile = ensure_profile(user)
    profile.is_premium = True
    profile.save(update_fields=["is_premium"])
    return profile


def test_free_user_bi_403(api, token):
    r = api.post("/content/videos/import", {"url": URL}, token=token)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "premium_required"


def test_link_khong_hop_le_422(api, token, premium):
    r = api.post("/content/videos/import", {"url": "https://example.com/abc"}, token=token)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_url"


def test_import_tao_video_ready_voi_phu_de_song_ngu(api, token, premium):
    r = api.post("/content/videos/import", {"url": URL}, token=token)
    assert r.status_code == 202, r.json()
    body = r.json()
    assert body["status"] == "ready"  # sync mode chạy xong ngay
    assert body["level"] == "B1"
    assert body["thumbnail_url"].endswith(f"/{YT}/hqdefault.jpg")

    video = Video.objects.get(youtube_id=YT)
    assert video.source == "user"
    assert video.is_free is False
    assert video.created_by == premium.user
    subs = list(video.subtitles.all())
    assert len(subs) == 3
    assert subs[1].text_en == "I am honored to be with you today."
    assert subs[1].text_vi.startswith("[vi] ")
    assert subs[1].ipa.startswith("/")
    assert video.duration_sec == 9
    assert UserVideoLibrary.objects.filter(user=premium.user, video=video).exists()


def test_detail_va_mine_cho_nguoi_them(api, token, premium):
    vid = api.post("/content/videos/import", {"url": URL}, token=token).json()["id"]

    detail = api.get(f"/content/videos/{vid}", token=token)
    assert detail.status_code == 200
    assert detail.json()["source"] == "user"
    assert len(detail.json()["subtitles"]) == 3

    mine = api.get("/content/videos/mine", token=token).json()
    assert [v["id"] for v in mine["items"]] == [vid]
    assert mine["quota"] == {"left": 1, "limit": 2}
    assert mine["can_import"] is True

    # Không xuất hiện trong thư viện chung.
    listing = api.get("/content/videos", token=token).json()
    assert listing["count"] == 0


def test_nguoi_khac_khong_xem_duoc_video_cua_toi(api, token, premium, password):
    from apps.accounts.models import User

    vid = api.post("/content/videos/import", {"url": URL}, token=token).json()["id"]
    other = User.objects.create_user(email="khac@example.com", password=password, full_name="Khác")
    other_token = api.post("/auth/token", {"email": other.email, "password": password}).json()[
        "access"
    ]
    assert api.get(f"/content/videos/{vid}", token=other_token).status_code == 404
    assert api.get("/content/videos/mine", token=other_token).json()["items"] == []


def test_video_da_ready_duoc_tai_dung_khong_ton_quota(api, token, premium, password):
    from apps.accounts.models import User

    api.post("/content/videos/import", {"url": URL}, token=token)
    other = User.objects.create_user(email="khac@example.com", password=password, full_name="Khác")
    other_profile = ensure_profile(other)
    other_profile.is_premium = True
    other_profile.save(update_fields=["is_premium"])
    other_token = api.post("/auth/token", {"email": other.email, "password": password}).json()[
        "access"
    ]

    r = api.post("/content/videos/import", {"url": f"https://youtu.be/{YT}"}, token=other_token)
    assert r.status_code == 202
    assert r.json()["status"] == "ready"
    assert Video.objects.filter(youtube_id=YT).count() == 1
    # get_or_create thư viện vẫn tạo 1 entry → quota vẫn tính (đã thêm hôm nay).
    assert (
        api.get("/content/videos/mine", token=other_token).json()["items"][0]["id"]
        == r.json()["id"]
    )


def test_het_quota_429(api, token, premium, monkeypatch):
    ids = iter(["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"])
    for _ in range(2):
        assert (
            api.post(
                "/content/videos/import", {"url": f"https://youtu.be/{next(ids)}"}, token=token
            ).status_code
            == 202
        )
    r = api.post("/content/videos/import", {"url": f"https://youtu.be/{next(ids)}"}, token=token)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "video_quota_exceeded"


def test_khong_co_phu_de_422(api, token, premium, monkeypatch):
    monkeypatch.setattr(video_import, "fetch_captions", lambda yid: None)
    r = api.post("/content/videos/import", {"url": URL}, token=token)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "no_captions"
    assert not Video.objects.filter(youtube_id=YT).exists()


def test_qua_dai_422(api, token, premium, settings):
    settings.VIDEO_IMPORT_MAX_SEC = 5
    r = api.post("/content/videos/import", {"url": URL}, token=token)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "too_long"


def test_khong_nhung_duoc_422(api, token, premium, monkeypatch):
    monkeypatch.setattr(video_import, "fetch_oembed", lambda yid: None)
    r = api.post("/content/videos/import", {"url": URL}, token=token)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "not_embeddable"


def test_preview(api, token, premium):
    r = api.get(f"/content/videos/preview?url={URL}", token=token)
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Steve Jobs Stanford Speech"
    assert body["has_english_captions"] is True
    assert body["duration_sec"] == 9
    assert body["reject_code"] == ""


def test_llm_loi_thi_video_failed(api, token, premium, monkeypatch):
    from apps.ai import llm

    def boom(*a, **k):
        raise llm.AIUpstreamError("down")

    monkeypatch.setattr(llm, "complete", boom)
    r = api.post("/content/videos/import", {"url": URL}, token=token)
    assert r.status_code == 202
    assert r.json()["status"] == "failed"
    assert r.json()["error_code"] == "translate_failed"
    assert r.json()["error_message"]
    # Chi tiết vẫn trả về nhưng không có phụ đề.
    detail = api.get(f"/content/videos/{r.json()['id']}", token=token).json()
    assert detail["status"] == "failed" and detail["subtitles"] == []


def test_xoa_khoi_thu_vien(api, token, premium):
    vid = api.post("/content/videos/import", {"url": URL}, token=token).json()["id"]
    assert api.delete(f"/content/videos/{vid}", token=token).status_code == 204
    assert api.get("/content/videos/mine", token=token).json()["items"] == []
    assert api.get(f"/content/videos/{vid}", token=token).status_code == 404
    assert api.delete(f"/content/videos/{vid}", token=token).status_code == 404


def test_parse_youtube_id():
    assert video_import.parse_youtube_id("https://youtu.be/UF8uR6Z6KLc?t=1") == YT
    assert video_import.parse_youtube_id("https://www.youtube.com/shorts/UF8uR6Z6KLc") == YT
    assert video_import.parse_youtube_id("UF8uR6Z6KLc") == YT
    assert video_import.parse_youtube_id("https://vimeo.com/123") is None
