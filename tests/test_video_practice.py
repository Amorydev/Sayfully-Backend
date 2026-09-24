"""Tiến độ luyện video theo câu (apps.learning.video_practice) qua POST /learn/practice."""

import pytest

from apps.content.models import Level, Video, VideoSubtitle
from apps.learning.models import VideoPracticeResult

pytestmark = pytest.mark.django_db


@pytest.fixture
def token(api, user, password) -> str:
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


@pytest.fixture
def video():
    a1 = Level.objects.create(code="A1", name_vi="Sơ cấp", order=1, is_free=True)
    vd = Video.objects.create(
        level=a1, youtube_id="aaaaaaaaaaa", title_vi="Sân bay", title_en="Airport"
    )
    for i, text in enumerate(["Good morning.", "Here you are.", "Thank you."], start=1):
        VideoSubtitle.objects.create(
            video=vd, order=i, start_ms=i * 1000, end_ms=i * 1000 + 900, text_en=text, text_vi="…"
        )
    return vd


def _practice(api, token, video_id, order, kind, score):
    return api.post(
        "/learn/practice",
        {"kind": kind, "score": score, "duration_sec": 5, "ref_id": f"video:{video_id}:{order}"},
        token=token,
    )


def test_practice_luu_ket_qua_tot_nhat_theo_cau(api, token, user, video):
    assert _practice(api, token, video.id, 1, "shadowing", 60).status_code == 200
    assert _practice(api, token, video.id, 1, "shadowing", 85).status_code == 200
    assert _practice(api, token, video.id, 1, "shadowing", 40).status_code == 200
    row = VideoPracticeResult.objects.get(user=user, video=video, mode="shadowing", order=1)
    assert row.percent == 85 and row.attempts == 3


def test_list_va_detail_tra_tien_do(api, token, video):
    _practice(api, token, video.id, 1, "shadowing", 78)
    _practice(api, token, video.id, 2, "shadowing", 90)
    _practice(api, token, video.id, 1, "dictation", 60)

    item = api.get("/content/videos", token=token).json()["items"][0]
    assert item["sentence_count"] == 3
    assert item["practice"] == {"shadowing_done": 2, "dictation_done": 1, "last_mode": "dictation"}

    detail = api.get(f"/content/videos/{video.id}", token=token).json()["practice"]
    assert detail["shadowing"] == [{"order": 1, "percent": 78}, {"order": 2, "percent": 90}]
    assert detail["dictation"] == [{"order": 1, "percent": 60}]
    assert detail["last_mode"] == "dictation"


def test_ref_id_khac_hoac_kind_khac_khong_ghi(api, token, user, video):
    _practice(api, token, video.id, 1, "speaking", 80)  # kind không phải mode video
    api.post("/learn/practice", {"kind": "shadowing", "score": 80, "ref_id": "deck:1"}, token=token)
    api.post(
        "/learn/practice",
        {"kind": "dictation", "score": 80, "ref_id": "video:999999:1"},
        token=token,
    )
    assert not VideoPracticeResult.objects.filter(user=user).exists()


def test_video_chua_luyen_tra_mac_dinh(api, token, video):
    item = api.get("/content/videos", token=token).json()["items"][0]
    assert item["practice"] == {"shadowing_done": 0, "dictation_done": 0, "last_mode": None}


def test_home_videos_xep_noi_bat_nguoi_hoc_moi(api, token, video, password):
    from apps.accounts.models import User
    from apps.content.models import Video, VideoSubtitle

    a1 = video.level
    popular = Video.objects.create(
        level=a1, youtube_id="bbbbbbbbbbb", title_vi="Hot", title_en="Hot"
    )
    VideoSubtitle.objects.create(
        video=popular, order=1, start_ms=0, end_ms=900, text_en="Hi.", text_vi="…"
    )
    hot = Video.objects.create(
        level=a1,
        youtube_id="ccccccccccc",
        title_vi="Ghim",
        title_en="Pinned",
        is_featured=True,
        featured_order=1,
    )
    VideoSubtitle.objects.create(
        video=hot, order=1, start_ms=0, end_ms=900, text_en="Hey.", text_vi="…"
    )
    Video.objects.create(
        level=a1, youtube_id="ddddddddddd", title_vi="Rỗng", title_en="Empty"
    )  # không có phụ đề

    for i in range(5):
        u = User.objects.create_user(
            email=f"u{i}@example.com", password=password, full_name=f"U{i}"
        )
        t = api.post("/auth/token", {"email": u.email, "password": password}).json()["access"]
        api.post(
            "/learn/practice",
            {"kind": "dictation", "score": 80, "ref_id": f"video:{popular.id}:1"},
            token=t,
        )

    videos = api.get("/home", token=token).json()["videos"]
    assert [v["id"] for v in videos] == [hot.id, popular.id, video.id]
    assert [v["badge"] for v in videos] == ["featured", "popular", "new"]
    assert videos[1]["learner_count"] == 5 and videos[2]["sentence_count"] == 3
