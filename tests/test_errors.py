"""Hợp đồng lỗi: MỌI lỗi dưới /api/ phải là {"error": {code, message, details}}."""

from unittest.mock import patch

import pytest

from apps.common.exceptions import group_validation_errors

pytestmark = pytest.mark.django_db


def _err(resp):
    body = resp.json()
    assert set(body) == {"error"}, body
    assert set(body["error"]) == {"code", "message", "details"}, body
    return body["error"]


def test_422_gom_loi_theo_field(api):
    r = api.post("/auth/register", {"email": "khong-phai-email", "password": "1"})
    assert r.status_code == 422
    e = _err(r)
    assert e["code"] == "validation_error"
    assert e["details"]["email"] == ["Email không hợp lệ"]
    assert any("ký tự" in m for m in e["details"]["password"])


def test_422_thieu_truong_bat_buoc(api):
    r = api.post("/auth/register", {})
    assert r.status_code == 422
    e = _err(r)
    assert e["details"]["email"] == ["Trường này là bắt buộc"]
    assert e["details"]["password"] == ["Trường này là bắt buộc"]


def test_401_thieu_header_authorization(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert _err(r)["code"] == "token_missing"


def test_401_token_rac_giu_code_cu_the(api):
    r = api.get("/auth/me", token="abc")
    assert r.status_code == 401
    assert _err(r)["code"] == "token_invalid"


def test_404_route_la_tra_json(client):
    r = client.get("/api/v1/khong-ton-tai")
    assert r.status_code == 404
    assert r["Content-Type"].startswith("application/json")
    assert _err(r)["code"] == "not_found"


def test_405_sai_method_tra_json_va_giu_allow(client):
    r = client.get("/api/v1/auth/token")
    assert r.status_code == 405
    assert _err(r)["code"] == "method_not_allowed"
    assert "POST" in r["Allow"]


def test_400_json_hong(client):
    r = client.post("/api/v1/auth/token", data="{hong", content_type="application/json")
    assert r.status_code == 400
    e = _err(r)
    assert e["code"] == "bad_request"
    assert "JSON" in e["message"]


def test_500_loi_chua_xu_ly_tra_envelope(api, settings):
    settings.DEBUG = False
    with patch("apps.accounts.services.authenticate_password", side_effect=RuntimeError("nổ")):
        r = api.post("/auth/token", {"email": "a@b.co", "password": "x"})
    assert r.status_code == 500
    e = _err(r)
    assert e["code"] == "internal_error"
    assert "nổ" not in e["message"]  # prod không lộ chi tiết


def test_500_debug_lo_ten_loi_de_dev(api, settings):
    settings.DEBUG = True
    with patch("apps.accounts.services.authenticate_password", side_effect=RuntimeError("nổ")):
        r = api.post("/auth/token", {"email": "a@b.co", "password": "x"})
    assert r.status_code == 500
    assert "RuntimeError: nổ" == _err(r)["message"]


def test_ngoai_api_khong_bi_boc(client):
    r = client.get("/khong-ton-tai")
    assert r.status_code == 404
    assert not r["Content-Type"].startswith("application/json")


def test_gom_loi_lo_long_va_query():
    errors = [
        {
            "type": "missing",
            "loc": ["body", "data", "answers", 0, "rating"],
            "msg": "Field required",
        },
        {"type": "int_parsing", "loc": ["query", "limit"], "msg": "x"},
        {"type": "greater_than_equal", "loc": ["query", "offset"], "msg": "x", "ctx": {"ge": 0}},
        {"type": "missing", "loc": ["body", "data"], "msg": "Field required"},
    ]
    g = group_validation_errors(errors)
    assert g["answers.0.rating"] == ["Trường này là bắt buộc"]
    assert g["limit"] == ["Phải là số"]
    assert g["offset"] == ["Phải lớn hơn hoặc bằng 0"]
    assert g["__all__"] == ["Trường này là bắt buộc"]
