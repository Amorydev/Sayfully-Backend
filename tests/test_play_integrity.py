"""Play Integrity trên các endpoint nộp điểm game.

Không gọi Google: `decode_token` được monkeypatch trả payload mẫu; `evaluate` test thẳng.
"""

import pytest

from apps.gamification import integrity
from apps.gamification.models import Game, GameScore

NOW_MS = 1_700_000_000_000


@pytest.fixture
def token(api, user, password):
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


def _game(code="word_rain"):
    return Game.objects.create(code=code, title_vi="Mưa từ", description_vi="x", kind="reflex")


def _payload(request_hash, **overrides):
    payload = {
        "requestDetails": {
            "requestPackageName": "amoryzenith.sayfully.app",
            "requestHash": request_hash,
            "timestampMillis": str(NOW_MS),
        },
        "appIntegrity": {"appRecognitionVerdict": "PLAY_RECOGNIZED"},
        "deviceIntegrity": {"deviceRecognitionVerdict": ["MEETS_DEVICE_INTEGRITY"]},
    }
    for section, values in overrides.items():
        payload[section].update(values)
    return payload


# ---------------------------------------------------------------- evaluate (thuần)


def test_evaluate_ok():
    assert integrity.evaluate(_payload("h"), "h", now_ms=NOW_MS) == integrity.OK


def test_evaluate_hash_khac_noi_dung_request():
    assert integrity.evaluate(_payload("h"), "other", now_ms=NOW_MS) == integrity.MISMATCH


def test_evaluate_sai_package():
    p = _payload("h", requestDetails={"requestPackageName": "com.evil"})
    assert integrity.evaluate(p, "h", now_ms=NOW_MS) == integrity.MISMATCH


def test_evaluate_token_qua_han(settings):
    settings.PLAY_INTEGRITY_MAX_AGE_SEC = 600
    late = NOW_MS + 601 * 1000
    assert integrity.evaluate(_payload("h"), "h", now_ms=late) == integrity.STALE


def test_evaluate_app_khong_phai_ban_play():
    p = _payload("h", appIntegrity={"appRecognitionVerdict": "UNRECOGNIZED_VERSION"})
    assert integrity.evaluate(p, "h", now_ms=NOW_MS) == integrity.APP_UNRECOGNIZED


def test_evaluate_thiet_bi_khong_dat():
    p = _payload("h", deviceIntegrity={"deviceRecognitionVerdict": []})
    assert integrity.evaluate(p, "h", now_ms=NOW_MS) == integrity.DEVICE_UNMET


def test_request_hash_khop_dinh_dang_client():
    # Chuỗi này được app dựng y hệt (IntegrityRequestHash.kt) — đổi một bên phải đổi cả hai.
    assert (
        integrity.score_request_hash("word_rain", 800, 60, "A1", 3, True)
        == "word_rain|800|60|A1|3|true"
    )
    assert (
        integrity.score_request_hash("word_rain", 5, 0, None, None, False)
        == "word_rain|5|0|||false"
    )
    assert integrity.match_pairs_request_hash(7, "easy", 12, 40) == "match_pairs|7|easy|12|40"


# ---------------------------------------------------------------- endpoint


@pytest.fixture
def decode(monkeypatch):
    """Giả lập Google: trả payload hợp lệ cho đúng request hash mà token mã hoá."""
    monkeypatch.setattr(integrity, "decode_token", lambda token: _payload(token))
    monkeypatch.setattr(integrity.time, "time", lambda: NOW_MS / 1000)


def test_mode_log_khong_token_van_ghi_diem(api, token, user, settings):
    settings.PLAY_INTEGRITY_MODE = "log"
    _game()
    r = api.post("/games/word_rain/scores", {"score": 800, "duration_sec": 60}, token=token)
    assert r.status_code == 200
    assert GameScore.objects.get(user=user).integrity == integrity.MISSING


def test_mode_off_bo_qua(api, token, user, settings):
    settings.PLAY_INTEGRITY_MODE = "off"
    _game()
    api.post("/games/word_rain/scores", {"score": 800}, token=token)
    assert GameScore.objects.get(user=user).integrity == integrity.SKIPPED


def test_mode_enforce_thieu_token_403(api, token, user, settings):
    settings.PLAY_INTEGRITY_MODE = "enforce"
    _game()
    r = api.post("/games/word_rain/scores", {"score": 800}, token=token)
    assert r.status_code == 403 and r.json()["error"]["code"] == "integrity_failed"
    assert not GameScore.objects.exists()


def test_mode_enforce_token_hop_le(api, token, user, settings, decode):
    settings.PLAY_INTEGRITY_MODE = "enforce"
    _game()
    r = api.post(
        "/games/word_rain/scores",
        {"score": 800, "duration_sec": 60, "level": "A1", "stage_index": 3},
        token=token,
        headers={"X-Integrity-Token": "word_rain|800|60|A1|3|true"},
    )
    assert r.status_code == 200
    assert GameScore.objects.get(user=user).integrity == integrity.OK


def test_mode_enforce_token_cua_request_khac_403(api, token, user, settings, decode):
    """Replay: token xin cho ván 100 điểm, gửi kèm ván 9000 điểm."""
    settings.PLAY_INTEGRITY_MODE = "enforce"
    _game()
    r = api.post(
        "/games/word_rain/scores",
        {"score": 9000},
        token=token,
        headers={"X-Integrity-Token": "word_rain|100|0|||true"},
    )
    assert r.status_code == 403


def test_mode_log_google_loi_ghi_invalid(api, token, user, settings, monkeypatch):
    settings.PLAY_INTEGRITY_MODE = "log"
    monkeypatch.setattr(
        integrity, "decode_token", lambda t: (_ for _ in ()).throw(RuntimeError("down"))
    )
    _game()
    r = api.post(
        "/games/word_rain/scores", {"score": 10}, token=token, headers={"X-Integrity-Token": "x"}
    )
    assert r.status_code == 200
    assert GameScore.objects.get(user=user).integrity == integrity.INVALID
