"""12 endpoint auth, kiểm cả 2 chế độ client."""

import pytest
from django.conf import settings

from apps.accounts.models import RefreshToken, User

pytestmark = pytest.mark.django_db

NEW = {"email": "moi@example.com", "password": "MatKhauRatManh123", "full_name": "Tân Binh"}


# ------------------------------------------------------------------ đăng ký / đăng nhập
def test_dang_ky_tra_token_va_tao_profile(api):
    r = api.post("/auth/register", NEW)
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["access"] and body["refresh"] and body["token_type"] == "Bearer"
    profile = User.objects.get(email=NEW["email"]).profile
    assert profile.cefr_level == "A1"
    assert profile.onboarding_completed is False


def test_dang_ky_trung_email_bi_409(api, user):
    r = api.post("/auth/register", {**NEW, "email": user.email})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_taken"


def test_mat_khau_qua_ngan_bi_tu_choi(api):
    r = api.post("/auth/register", {**NEW, "password": "ngan"})
    assert r.status_code == 422


def test_dang_nhap_dung(api, user, password):
    r = api.post("/auth/token", {"email": user.email, "password": password})
    assert r.status_code == 200 and r.json()["access"]


def test_dang_nhap_sai_mat_khau(api, user):
    r = api.post("/auth/token", {"email": user.email, "password": "sai-be-bet"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


# ------------------------------------------------------------------ 2 chế độ client
def test_mobile_nhan_refresh_trong_body(api, user, password):
    r = api.post("/auth/token", {"email": user.email, "password": password})
    assert r.json()["refresh"] is not None
    assert settings.REFRESH_COOKIE_NAME not in r.cookies


def test_web_nhan_refresh_trong_cookie_httponly(web_api, user, password):
    r = web_api.post("/auth/token", {"email": user.email, "password": password})
    assert r.json()["refresh"] is None, "web KHÔNG được nhận refresh trong body"
    cookie = r.cookies[settings.REFRESH_COOKIE_NAME]
    assert cookie["httponly"], "cookie phải httpOnly để chống XSS"
    assert cookie["path"] == settings.REFRESH_COOKIE_PATH


# ------------------------------------------------------------------ me
def test_me_can_token(api):
    assert api.get("/auth/me").status_code == 401


def test_me_tra_ho_so_va_profile(api, user, password):
    access = api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]
    body = api.get("/auth/me", token=access).json()
    assert body["email"] == user.email
    assert body["profile"]["hearts"] == 5 and body["profile"]["is_premium"] is False
    assert body["profile"]["onboarding_completed"] is False


def test_hoan_tat_onboarding_cap_nhat_trinh_do_hien_tai(api, user, password):
    access = api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]

    response = api.patch(
        "/me/preferences",
        {"cefr_level": "A2", "onboarding_completed": True},
        token=access,
    )

    assert response.status_code == 200, response.content
    assert response.json()["cefr_level"] == "A2"
    assert response.json()["onboarding_completed"] is True
    user.profile.refresh_from_db()
    assert user.profile.onboarding_completed_at is not None


# ------------------------------------------------------------------ refresh
def test_refresh_mobile_tra_token_moi(api, user, password):
    old = api.post("/auth/token", {"email": user.email, "password": password}).json()["refresh"]
    r = api.post("/auth/refresh", {"refresh": old})
    assert r.status_code == 200 and r.json()["refresh"] != old


def test_dung_lai_refresh_cu_bi_chan(api, user, password):
    old = api.post("/auth/token", {"email": user.email, "password": password}).json()["refresh"]
    api.post("/auth/refresh", {"refresh": old})
    r = api.post("/auth/refresh", {"refresh": old})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "refresh_reused"


def test_web_thieu_cookie_bi_401(web_api):
    r = web_api.post("/auth/refresh", {})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "refresh_missing"


# ------------------------------------------------------------------ đăng xuất
def test_logout_thu_hoi_refresh(api, user, password):
    tokens = api.post("/auth/token", {"email": user.email, "password": password}).json()
    assert api.post("/auth/logout", {"refresh": tokens["refresh"]}).status_code == 200
    assert api.post("/auth/refresh", {"refresh": tokens["refresh"]}).status_code == 401


def test_logout_all_thu_hoi_moi_thiet_bi(api, user, password):
    t1 = api.post("/auth/token", {"email": user.email, "password": password}).json()
    t2 = api.post("/auth/token", {"email": user.email, "password": password}).json()
    assert api.post("/auth/logout-all", token=t1["access"]).status_code == 200
    for t in (t1, t2):
        assert api.post("/auth/refresh", {"refresh": t["refresh"]}).status_code == 401


# ------------------------------------------------------------------ mật khẩu
def test_quen_mat_khau_khong_lo_email_ton_tai(api, user):
    a = api.post("/auth/password/forgot", {"email": user.email})
    b = api.post("/auth/password/forgot", {"email": "khong-ton-tai@example.com"})
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json(), "hai phản hồi phải giống hệt nhau"


def test_doi_mat_khau_thu_hoi_moi_phien(api, user, password):
    t = api.post("/auth/token", {"email": user.email, "password": password}).json()
    r = api.post(
        "/auth/change-password",
        {"old_password": password, "new_password": "MatKhauMoiRatManh456"},
        token=t["access"],
    )
    assert r.status_code == 200
    assert api.post("/auth/refresh", {"refresh": t["refresh"]}).status_code == 401
    user.refresh_from_db()
    assert user.check_password("MatKhauMoiRatManh456")


def test_doi_mat_khau_sai_mat_khau_cu(api, user, password):
    t = api.post("/auth/token", {"email": user.email, "password": password}).json()
    r = api.post(
        "/auth/change-password",
        {"old_password": "sai", "new_password": "MatKhauMoiRatManh456"},
        token=t["access"],
    )
    assert r.status_code == 401


# ------------------------------------------------------------------ xoá tài khoản
def test_xoa_tai_khoan_an_danh_va_thu_hoi(api, user, password):
    t = api.post("/auth/token", {"email": user.email, "password": password}).json()
    assert api.delete("/auth/delete-account", token=t["access"]).status_code == 200

    user.refresh_from_db()
    assert user.deleted_at is not None and user.is_active is False
    assert user.email.startswith("deleted_")
    assert not RefreshToken.objects.filter(user=user, revoked_at__isnull=True).exists()
    assert api.get("/auth/me", token=t["access"]).status_code == 401


def test_email_duoc_giai_phong_de_dang_ky_lai(api, user, password):
    email_cu = user.email
    t = api.post("/auth/token", {"email": user.email, "password": password}).json()
    api.delete("/auth/delete-account", token=t["access"])
    r = api.post("/auth/register", {**NEW, "email": email_cu})
    assert r.status_code == 200, "sau khi xoá, email phải đăng ký lại được"


# ------------------------------------------------------------------ rate limit
def test_rate_limit_chan_do_mat_khau(api, user, settings):
    settings.RATELIMIT_ENABLE = True
    codes = [
        api.post("/auth/token", {"email": user.email, "password": "sai"}).status_code
        for _ in range(7)
    ]
    assert 429 in codes, f"phải bị chặn sau vài lần, nhận được: {codes}"


# ------------------------------------------------------------------ luyện nói theo chủ đề (C8a)
def test_speaking_topics_liet_ke_va_cong_tien_do(api, user, password):
    from apps.content.models import Level, ShadowingDeck, ShadowingSentence
    from apps.learning.models import SpeakingSentenceResult

    lv = Level.objects.create(code="A1", name_vi="Sơ cấp", order=1, is_free=True)
    deck = ShadowingDeck.objects.create(
        level=lv,
        order=1,
        title_en="Greetings",
        title_vi="Chào hỏi",
        icon="greeting",
        background_url="speaking/greeting.webp",
        est_seconds=180,
        is_free=True,
    )
    for j in range(4):
        ShadowingSentence.objects.create(deck=deck, order=j, text_en=f"s{j}", text_vi=f"c{j}")
    premium = ShadowingDeck.objects.create(
        level=lv,
        order=2,
        title_en="Interview",
        title_vi="Phỏng vấn",
        is_free=False,
    )
    ShadowingSentence.objects.create(deck=premium, order=0, text_en="x", text_vi="y")

    access = api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]

    body = api.get("/learn/speaking/topics", token=access).json()
    assert body["week_practiced"] == 0
    assert body["by_lesson"] == []  # tab "Theo bài học" trống ở v1
    basic = {t["title_vi"]: t for t in body["basic"]}
    assert basic["Chào hỏi"]["sentence_count"] == 4
    assert basic["Chào hỏi"]["est_minutes"] == 3
    assert basic["Chào hỏi"]["level"] == "A1"
    assert basic["Chào hỏi"]["title_en"] == "Greetings"
    assert basic["Chào hỏi"]["phrase_preview"] == "s0"
    assert basic["Chào hỏi"]["background_url"].endswith("/speaking/greeting.webp")
    assert basic["Chào hỏi"]["is_premium"] is False
    assert basic["Chào hỏi"]["done"] == 0 and basic["Chào hỏi"]["total"] == 4
    assert basic["Phỏng vấn"]["is_premium"] is True
    # Gợi ý: chỉ chủ đề chưa xong & không khoá → có "Chào hỏi", không có "Phỏng vấn" (khoá)
    suggested_titles = {t["title_vi"] for t in body["suggested"]}
    assert "Chào hỏi" in suggested_titles and "Phỏng vấn" not in suggested_titles

    # luyện 1 câu của chủ đề → tiến độ 1/4, hero tuần +1
    r = api.post(
        "/learn/practice",
        {"kind": "speaking", "score": 80, "duration_sec": 30, "deck_id": deck.id},
        token=access,
    )
    assert r.status_code == 200
    body2 = api.get("/learn/speaking/topics", token=access).json()
    greet = next(t for t in body2["basic"] if t["title_vi"] == "Chào hỏi")
    assert greet["done"] == 1 and greet["percent"] == 25
    assert body2["week_practiced"] == 1

    # đọc lại CÙNG câu (ref_id=0) → tiến độ vẫn 1/4, chỉ giữ điểm tốt nhất
    api.post(
        "/learn/practice",
        {"kind": "speaking", "score": 95, "duration_sec": 20, "ref_id": "0", "deck_id": deck.id},
        token=access,
    )
    api.post(
        "/learn/practice",
        {"kind": "speaking", "score": 60, "duration_sec": 20, "ref_id": "0", "deck_id": deck.id},
        token=access,
    )
    greet = next(
        t
        for t in api.get("/learn/speaking/topics", token=access).json()["basic"]
        if t["title_vi"] == "Chào hỏi"
    )
    assert greet["done"] == 1
    row = SpeakingSentenceResult.objects.get(deck=deck, order=0)
    assert row.percent == 95 and row.attempts == 2

    # sang câu khác → 2/4
    api.post(
        "/learn/practice",
        {"kind": "speaking", "score": 70, "duration_sec": 20, "ref_id": "1", "deck_id": deck.id},
        token=access,
    )
    greet = next(
        t
        for t in api.get("/learn/speaking/topics", token=access).json()["basic"]
        if t["title_vi"] == "Chào hỏi"
    )
    assert greet["done"] == 2 and greet["percent"] == 50


# ------------------------------------------------------------------ luyện nghe (C9a/C9)
def test_listening_topics_va_2_mode(api, user, password):
    from apps.content.models import Level, ListeningItem, ListeningTopic

    lv = Level.objects.create(code="A1", name_vi="Sơ cấp", order=1, is_free=True)
    topic = ListeningTopic.objects.create(
        level=lv,
        order=1,
        title_vi="Chào hỏi",
        icon="greeting",
        icon_url="listening/greeting.webp",
        est_seconds=240,
        is_free=True,
    )
    for j in range(3):
        ListeningItem.objects.create(
            topic=topic,
            order=j,
            text_en=f"Hello, nice to meet you {j}.",
            text_vi="Xin chào.",
            audio_us_path=f"audio/listen/greet_{j}.mp3",
            blank_index=3,
            options=["meet", "meat", "mit", "meal"],
            answer_index=0,
            skill_vi="Phân biệt âm vị",
        )
    premium = ListeningTopic.objects.create(
        level=lv,
        order=2,
        title_vi="Phỏng vấn",
        icon="interview",
        is_free=False,
    )
    ListeningItem.objects.create(
        topic=premium,
        order=0,
        text_en="Tell me about yourself.",
        text_vi="Giới thiệu.",
        blank_index=3,
        options=["yourself", "myself", "itself", "herself"],
        answer_index=0,
    )

    access = api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]

    body = api.get("/learn/listening/topics", token=access).json()
    assert body["week_practiced"] == 0
    assert body["by_lesson"] == []
    basic = {t["title_vi"]: t for t in body["basic"]}
    assert basic["Chào hỏi"]["item_count"] == 3
    assert basic["Chào hỏi"]["est_minutes"] == 4
    assert basic["Chào hỏi"]["level"] == "A1"
    assert basic["Chào hỏi"]["phrase_preview"] == "Hello, nice to meet you 0."
    assert basic["Chào hỏi"]["focus_vi"] == "Phân biệt âm vị"  # chưa đặt focus riêng → kỹ năng câu đầu
    assert basic["Chào hỏi"]["background_url"].endswith("/listening/greeting.webp")  # ảnh cũ nằm ở icon_url
    assert basic["Phỏng vấn"]["background_url"] is None
    assert basic["Chào hỏi"]["done_choose"] == 0 and basic["Chào hỏi"]["done_dictation"] == 0
    assert basic["Phỏng vấn"]["is_premium"] is True
    assert "Chào hỏi" in {t["title_vi"] for t in body["suggested"]}

    # mode choose → có blank_index + options + answer_index
    ch = api.get(f"/learn/listening/topics/{topic.id}?mode=choose", token=access).json()
    assert ch["mode"] == "choose" and ch["total"] == 3
    assert ch["items"][0]["blank_index"] == 3
    assert ch["items"][0]["options"] == ["meet", "meat", "mit", "meal"]
    assert ch["items"][0]["answer_index"] == 0

    # mode dictation → KHÔNG kèm blank/options
    di = api.get(f"/learn/listening/topics/{topic.id}?mode=dictation", token=access).json()
    assert di["mode"] == "dictation"
    assert di["items"][0]["blank_index"] is None and di["items"][0]["options"] == []

    # premium topic → 403
    assert (
        api.get(f"/learn/listening/topics/{premium.id}?mode=choose", token=access).status_code
        == 403
    )

    # nộp 1 câu mode choose → done_choose 1/3, week +1
    r = api.post(
        "/learn/practice",
        {"kind": "listening", "score": 90, "duration_sec": 20, "listening_topic_id": topic.id},
        token=access,
    )
    assert r.status_code == 200
    # nộp 1 câu mode dictation → done_dictation 1/3
    api.post(
        "/learn/practice",
        {"kind": "dictation", "score": 80, "duration_sec": 25, "listening_topic_id": topic.id},
        token=access,
    )
    body2 = api.get("/learn/listening/topics", token=access).json()
    greet = next(t for t in body2["basic"] if t["title_vi"] == "Chào hỏi")
    assert greet["done_choose"] == 1 and greet["done_dictation"] == 1
    assert body2["week_practiced"] == 2
