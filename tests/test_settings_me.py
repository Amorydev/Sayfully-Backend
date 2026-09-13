"""C49 Cài đặt: /auth/me phải trả đủ tuỳ chọn hiển thị để màn mở không cần gọi thêm."""

import pytest

pytestmark = pytest.mark.django_db


def _access(api, user, password):
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


def test_me_tra_tuy_chon_cai_dat(api, user, password):
    profile = api.get("/auth/me", token=_access(api, user, password)).json()["profile"]
    assert profile["show_ipa"] is True and profile["accent"] == "US"
    assert profile["ui_language"] == "vi"
    assert profile["reminder_enabled"] is True
    assert profile["reminder_time"] == "20:00"
    assert profile["streak_reminder"] is True and profile["event_notifications"] is True
    assert profile["daily_goal_words"] == 10


def test_me_phan_anh_thay_doi_tu_preferences(api, user, password):
    access = _access(api, user, password)
    api.patch("/me/preferences", {"show_ipa": False, "reminder_time": "07:30"}, token=access)
    profile = api.get("/auth/me", token=access).json()["profile"]
    assert profile["show_ipa"] is False
    assert profile["reminder_time"] == "07:30"
