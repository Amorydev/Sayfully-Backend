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
    r = api.post("/auth/change-password",
                 {"old_password": password, "new_password": "MatKhauMoiRatManh456"},
                 token=t["access"])
    assert r.status_code == 200
    assert api.post("/auth/refresh", {"refresh": t["refresh"]}).status_code == 401
    user.refresh_from_db()
    assert user.check_password("MatKhauMoiRatManh456")


def test_doi_mat_khau_sai_mat_khau_cu(api, user, password):
    t = api.post("/auth/token", {"email": user.email, "password": password}).json()
    r = api.post("/auth/change-password",
                 {"old_password": "sai", "new_password": "MatKhauMoiRatManh456"},
                 token=t["access"])
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
    codes = [api.post("/auth/token", {"email": user.email, "password": "sai"}).status_code
             for _ in range(7)]
    assert 429 in codes, f"phải bị chặn sau vài lần, nhận được: {codes}"
