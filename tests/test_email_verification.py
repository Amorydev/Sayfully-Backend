"""Xác minh email bằng mã 6 số sau khi đăng ký."""

import re
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import services
from apps.accounts.models import EmailVerification, User
from apps.accounts.social import SocialProfile

pytestmark = pytest.mark.django_db

NEW = {"email": "moi@example.com", "password": "MatKhauRatManh123", "full_name": "Tân Binh"}


def _register(api) -> str:
    r = api.post("/auth/register", NEW)
    assert r.status_code == 200, r.content
    return r.json()["access"]


def _code_from(mail) -> str:
    return re.search(r"\b(\d{6})\b", mail.body).group(1)


def test_dang_ky_gui_ma_va_chua_xac_minh(api, mailoutbox):
    token = _register(api)
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == [NEW["email"]]
    assert api.get("/auth/me", token=token).json()["email_verified"] is False


def test_nhap_dung_ma_thi_xac_minh(api, mailoutbox):
    token = _register(api)
    r = api.post("/auth/email/verify", {"code": _code_from(mailoutbox[0])}, token=token)
    assert r.status_code == 200, r.content
    assert r.json()["email_verified"] is True
    assert not EmailVerification.objects.exists()


def test_nhap_sai_bao_so_lan_con_lai_roi_khoa(api, mailoutbox):
    token = _register(api)
    wrong = "000000" if _code_from(mailoutbox[0]) != "000000" else "111111"
    r = api.post("/auth/email/verify", {"code": wrong}, token=token)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "verify_code_invalid"
    assert r.json()["error"]["details"]["attempts_left"] == ["4"]
    for _ in range(4):
        r = api.post("/auth/email/verify", {"code": wrong}, token=token)
    assert r.json()["error"]["code"] == "verify_code_locked"
    # Đã khoá thì mã đúng cũng không nhận nữa.
    r = api.post("/auth/email/verify", {"code": _code_from(mailoutbox[0])}, token=token)
    assert r.json()["error"]["code"] == "verify_code_locked"


def test_ma_het_han(api, mailoutbox):
    token = _register(api)
    EmailVerification.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    r = api.post("/auth/email/verify", {"code": _code_from(mailoutbox[0])}, token=token)
    assert r.json()["error"]["code"] == "verify_code_expired"


def test_ma_sai_dinh_dang_bi_422(api):
    token = _register(api)
    assert api.post("/auth/email/verify", {"code": "12ab"}, token=token).status_code == 422


def test_gui_lai_phai_doi_60_giay_va_ma_cu_mat_hieu_luc(api, mailoutbox):
    token = _register(api)
    r = api.post("/auth/email/resend", token=token)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "verify_resend_too_soon"
    assert int(r.json()["error"]["details"]["retry_after"][0]) > 0

    EmailVerification.objects.update(sent_at=timezone.now() - timedelta(seconds=61))
    assert api.post("/auth/email/resend", token=token).status_code == 200
    assert len(mailoutbox) == 2
    old, new = _code_from(mailoutbox[0]), _code_from(mailoutbox[1])
    if old != new:
        r = api.post("/auth/email/verify", {"code": old}, token=token)
        assert r.json()["error"]["code"] == "verify_code_invalid"
    assert api.post("/auth/email/verify", {"code": new}, token=token).status_code == 200


def test_tai_khoan_cu_va_da_xac_minh_khong_gui_ma(api, user, password, mailoutbox):
    token = api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]
    assert api.get("/auth/me", token=token).json()["email_verified"] is True
    assert api.post("/auth/email/resend", token=token).status_code == 200
    assert mailoutbox == []


def test_dang_ky_lai_email_chua_xac_minh_ghi_de_tai_khoan(api):
    first = api.post("/auth/register", NEW).json()["refresh"]
    r = api.post("/auth/register", {**NEW, "password": "MatKhauMoi456789"})
    assert r.status_code == 200, r.content
    assert User.objects.filter(email=NEW["email"]).count() == 1
    assert User.objects.get(email=NEW["email"]).check_password("MatKhauMoi456789")
    # Phiên của lần đăng ký trước bị thu hồi.
    assert api.post("/auth/refresh", {"refresh": first}).status_code == 401


def test_email_da_xac_minh_van_bi_409(api, mailoutbox):
    token = _register(api)
    api.post("/auth/email/verify", {"code": _code_from(mailoutbox[0])}, token=token)
    assert api.post("/auth/register", NEW).json()["error"]["code"] == "email_taken"


def test_dang_nhap_google_xac_minh_luon_email_cho_xac_minh(api):
    _register(api)
    user, created = services.login_or_create_social(
        SocialProfile(provider="google", uid="g-1", email=NEW["email"], email_verified=True)
    )
    assert created is False
    user.refresh_from_db()
    assert user.email_verified is True
