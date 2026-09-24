"""Play Integrity cho các endpoint nộp điểm game.

Luồng: app Android xin token từ Play (Standard API) với `requestHash` = chuỗi canonical của
nội dung request (xem `score_request_hash` / `match_pairs_request_hash` — client Kotlin dựng
đúng chuỗi này). Máy chủ gửi token cho Play Integrity API giải mã, rồi đối chiếu:
package name, requestHash, tuổi token, verdict app (PLAY_RECOGNIZED) và thiết bị
(MEETS_DEVICE_INTEGRITY).

Chế độ trong settings.PLAY_INTEGRITY_MODE:
- off: không đụng header.
- log: ghi verdict vào GameScore.integrity để theo dõi, không chặn.
- enforce: verdict khác `ok` → 403 `integrity_failed`.
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any

from django.conf import settings

from apps.common.exceptions import Forbidden

log = logging.getLogger(__name__)

HEADER = "X-Integrity-Token"
META_KEY = "HTTP_X_INTEGRITY_TOKEN"
SCOPE = "https://www.googleapis.com/auth/playintegrity"
DECODE_URL = "https://playintegrity.googleapis.com/v1/{package}:decodeIntegrityToken"

# Verdict lưu trong GameScore.integrity (CharField 16).
OK = "ok"
SKIPPED = "skipped"  # PLAY_INTEGRITY_MODE=off
MISSING = "missing"  # không có header (iOS, web, build cũ)
INVALID = "invalid"  # Play không giải mã được / lỗi mạng / chưa cấu hình
MISMATCH = "mismatch"  # requestHash hoặc package khác nội dung request
STALE = "stale"  # token quá PLAY_INTEGRITY_MAX_AGE_SEC
APP_UNRECOGNIZED = "app"  # bản build không phải bản đã lên Play (sideload, dev, repack)
DEVICE_UNMET = "device"  # thiết bị root / emulator / không đạt MEETS_DEVICE_INTEGRITY


def score_request_hash(
    code: str,
    score: int,
    duration_sec: int,
    level: str | None,
    stage_index: int | None,
    cleared: bool,
) -> str:
    """Chuỗi ràng buộc token với nội dung POST /games/{code}/scores. Phải khớp từng ký tự
    với `IntegrityRequestHash.forScore` phía app."""
    return "|".join(
        [
            code,
            str(score),
            str(duration_sec),
            level or "",
            "" if stage_index is None else str(stage_index),
            "true" if cleared else "false",
        ]
    )


def match_pairs_request_hash(stage_id: int, difficulty: str, moves: int, duration_sec: int) -> str:
    """Chuỗi ràng buộc cho POST /match-pairs/stages/{id}/result — khớp
    `IntegrityRequestHash.forMatchPairs` phía app."""
    return "|".join(["match_pairs", str(stage_id), difficulty, str(moves), str(duration_sec)])


def check(request, expected_hash: str) -> str:
    """Trả verdict cho request; ném 403 ở chế độ enforce khi verdict khác `ok`."""
    mode = settings.PLAY_INTEGRITY_MODE
    if mode == "off":
        return SKIPPED

    token = request.META.get(META_KEY, "")
    verdict = MISSING if not token else _verify(token, expected_hash)

    if mode == "enforce" and verdict != OK:
        raise Forbidden("Không xác minh được tính toàn vẹn của ứng dụng", code="integrity_failed")
    return verdict


def _verify(token: str, expected_hash: str) -> str:
    try:
        payload = decode_token(token)
    except Exception:  # noqa: BLE001 — lỗi mạng/cấu hình chỉ nên hạ verdict, không 500
        log.warning("Play Integrity: không giải mã được token", exc_info=True)
        return INVALID
    return evaluate(payload, expected_hash)


def evaluate(payload: dict[str, Any], expected_hash: str, now_ms: int | None = None) -> str:
    """Đối chiếu payload đã giải mã (tách riêng để test không cần gọi Google)."""
    details = payload.get("requestDetails") or {}
    if details.get("requestPackageName") != settings.PLAY_INTEGRITY_PACKAGE_NAME:
        return MISMATCH
    if details.get("requestHash") != expected_hash:
        return MISMATCH

    issued = int(details.get("timestampMillis") or 0)
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    if abs(now - issued) > settings.PLAY_INTEGRITY_MAX_AGE_SEC * 1000:
        return STALE

    app = payload.get("appIntegrity") or {}
    if app.get("appRecognitionVerdict") != "PLAY_RECOGNIZED":
        return APP_UNRECOGNIZED

    device = payload.get("deviceIntegrity") or {}
    if "MEETS_DEVICE_INTEGRITY" not in (device.get("deviceRecognitionVerdict") or []):
        return DEVICE_UNMET

    return OK


def decode_token(token: str) -> dict[str, Any]:
    """Gọi Play Integrity API giải mã token. Trả `tokenPayloadExternal`."""
    session = _session()
    url = DECODE_URL.format(package=settings.PLAY_INTEGRITY_PACKAGE_NAME)
    resp = session.post(url, json={"integrityToken": token}, timeout=10)
    resp.raise_for_status()
    return resp.json()["tokenPayloadExternal"]


@lru_cache(maxsize=1)
def _session():
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    path = settings.PLAY_INTEGRITY_SERVICE_ACCOUNT_FILE
    if not path:
        raise RuntimeError("Chưa cấu hình PLAY_INTEGRITY_SERVICE_ACCOUNT_FILE")
    creds = service_account.Credentials.from_service_account_file(path, scopes=[SCOPE])
    return AuthorizedSession(creds)
