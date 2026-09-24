"""Xác thực callback SSV (server-side verification) của AdMob.

Mạng quảng cáo gọi GET tới endpoint của ta khi người dùng **thật sự** xem xong quảng cáo.
Chữ ký ECDSA nằm trong query string; phần được ký là toàn bộ query **trước** ``&signature=``.
Khoá công khai lấy từ Google và cache trong tiến trình (khoá xoay vài tháng một lần).

Tắt xác thực (``ADS_SSV_REQUIRED=False``) chỉ dành cho máy dev — khi đó server tin client,
đủ để chạy luồng nhưng không được bật ở môi trường thật.
"""

import base64
import json
import logging
import time
import urllib.request
from urllib.parse import parse_qs

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from django.conf import settings

logger = logging.getLogger(__name__)

_KEY_CACHE: dict[str, str] = {}
_KEY_CACHE_AT = 0.0


class SsvError(Exception):
    """Callback không hợp lệ — chữ ký sai, khoá lạ, hoặc quá hạn."""


def _fetch_keys() -> dict[str, str]:
    """{key_id: pem}. Cache theo ``ADS_SSV_KEYS_TTL_SEC`` để không gọi Google mỗi lượt."""
    global _KEY_CACHE_AT
    now = time.time()
    if _KEY_CACHE and now - _KEY_CACHE_AT < settings.ADS_SSV_KEYS_TTL_SEC:
        return _KEY_CACHE
    with urllib.request.urlopen(settings.ADS_SSV_KEYS_URL, timeout=10) as resp:  # noqa: S310
        payload = json.loads(resp.read().decode())
    keys = {str(k["keyId"]): k["pem"] for k in payload.get("keys", [])}
    if keys:
        _KEY_CACHE.clear()
        _KEY_CACHE.update(keys)
        _KEY_CACHE_AT = now
    return _KEY_CACHE


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify(query_string: str, *, now: float | None = None) -> dict[str, str]:
    """Trả về các tham số đã parse nếu callback hợp lệ; ném :class:`SsvError` nếu không.

    Kiểm ba thứ: chữ ký khớp khoá công khai của Google, khoá còn trong danh sách hiện hành,
    và ``timestamp`` chưa quá cũ (chống phát lại).
    """
    params = {k: v[0] for k, v in parse_qs(query_string, keep_blank_values=True).items()}
    marker = "&signature="
    index = query_string.find(marker)
    if index < 0:
        raise SsvError("Thiếu chữ ký")
    signed_part = query_string[:index]

    stamp = params.get("timestamp", "")
    if stamp.isdigit():
        age = (now or time.time()) - int(stamp) / 1000
        if age > settings.ADS_SSV_MAX_AGE_SEC:
            raise SsvError("Callback quá cũ")

    if not settings.ADS_SSV_REQUIRED:
        return params

    pem = _fetch_keys().get(params.get("key_id", ""))
    if pem is None:
        raise SsvError("Không tìm thấy khoá công khai")
    try:
        public_key = load_pem_public_key(pem.encode())
        public_key.verify(
            _b64url_decode(params["signature"]),
            signed_part.encode(),
            ec.ECDSA(hashes.SHA256()),
        )
    except (InvalidSignature, KeyError, ValueError) as exc:
        raise SsvError("Chữ ký không hợp lệ") from exc
    return params
