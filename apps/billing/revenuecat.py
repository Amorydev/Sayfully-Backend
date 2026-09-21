"""Client RevenueCat REST v1 — chỉ dùng cho `POST /billing/sync`.

Hàm cấp module để test thay bằng hàm giả (như `create_payos_link`). Secret key đọc từ
`REVENUECAT_API_KEY`; trống → `StoreSyncFailed` để app hiện "cửa hàng chưa sẵn sàng".
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from django.conf import settings

from apps.common.exceptions import AppError

BASE_URL = "https://api.revenuecat.com/v1"
TIMEOUT_SEC = 10


class StoreSyncFailed(AppError):
    status_code = 503
    code = "store_sync_failed"


def fetch_subscriber(app_user_id: str) -> dict | None:
    """`GET /subscribers/{id}` → dict `subscriber`, None khi RevenueCat chưa biết user này."""
    key = getattr(settings, "REVENUECAT_API_KEY", "")
    if not key:
        raise StoreSyncFailed("Chưa cấu hình RevenueCat")
    url = f"{BASE_URL}/subscribers/{urllib.parse.quote(app_user_id, safe='')}"
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise StoreSyncFailed(f"RevenueCat trả {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise StoreSyncFailed("Không kết nối được RevenueCat") from exc
    return body.get("subscriber")


def parse_date(value) -> datetime | None:
    """RevenueCat trả ISO 8601 có hậu tố Z."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None
