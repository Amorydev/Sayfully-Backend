"""NinjaAPI gốc. Mỗi app đăng ký router ở đây.

Chuẩn tài liệu áp dụng cho MỌI endpoint:
- có `summary` và `description` tiếng Việt
- khai báo đủ mã lỗi (401/403/404/409/422/429) trỏ tới `ErrorOut`
- danh sách luôn phân trang bằng `limit`/`offset`
"""

from ninja import NinjaAPI

from apps.accounts.api import router as auth_router
from apps.accounts.auth import bearer_auth
from apps.billing.api import billing_router, webhooks_router
from apps.common.exceptions import register_exception_handlers
from apps.content.api import router as content_router
from apps.learning.api import router as learning_router

DESCRIPTION = """
Backend học tiếng Anh cho người Việt, theo khung CEFR **A1 → C2**.

### Hai loại client
Khai báo qua header `X-Client-Type`:

| Giá trị | Access token | Refresh token |
|---|---|---|
| `mobile` (mặc định) | `Authorization: Bearer <access>` | trả trong response body |
| `web` | `Authorization: Bearer <access>` | httpOnly cookie `sayfully_rt` |

### Hợp đồng lỗi
**Mọi** phản hồi lỗi (kể cả 422 validation, 404 route lạ, 405, 500) đều cùng một hình dạng:

```json
{"error": {"code": "invalid_credentials", "message": "Email hoặc mật khẩu không đúng", "details": {}}}
```

- `code` là hợp đồng — client phân nhánh trên trường này; `message` là tiếng Việt để hiển thị, có thể đổi.
- `details` chỉ có nội dung ở **422**: map `field → [lỗi]`, ví dụ `{"email": ["Email không hợp lệ"], "password": ["Tối thiểu 8 ký tự"]}`.

| HTTP | `code` chung | Khi nào |
|---|---|---|
| 400 | `bad_request` | JSON hỏng, yêu cầu sai |
| 401 | `token_missing` · `token_expired` · `token_invalid` · `refresh_*` · `invalid_credentials` · `account_inactive` | xem tag `auth` |
| 403 | `forbidden` · `premium_required` | thiếu quyền / cần Premium |
| 404 | `not_found` | không có tài nguyên hoặc route |
| 405 | `method_not_allowed` | sai method |
| 409 | `conflict` · `email_taken` · `already_claimed` · `insufficient_coins` | xung đột trạng thái |
| 422 | `validation_error` | dữ liệu sai — đọc `details` |
| 429 | `rate_limited` | quá 5 yêu cầu/phút/IP |
| 500 | `internal_error` | lỗi hệ thống |
| 503 | `feature_disabled` · `service_unavailable` | tính năng tắt (AI) / dịch vụ ngoài lỗi |

Bảng mã lỗi đầy đủ theo từng nhóm: `ENDPOINTS.md` §13.
"""

TAGS = [
    {"name": "auth", "description": "Đăng ký, đăng nhập, token, mật khẩu, xoá tài khoản."},
    {"name": "content", "description": "Nội dung học: lộ trình, từ vựng, ngữ pháp, đọc, truyện, video, tra cứu."},
    {"name": "learning", "description": "Lõi học tập: trang chủ, lộ trình, bài học, ôn tập, hoạt động."},
    {"name": "billing", "description": "Thanh toán: gói Premium, đăng ký, mã quà tặng, webhook."},
]

api = NinjaAPI(
    title="Sayfully API",
    version="1.0.0",
    description=DESCRIPTION,
    docs_url="/docs",
    openapi_extra={"tags": TAGS},
)

register_exception_handlers(api)


api.add_router("/auth", auth_router, tags=["auth"])
api.add_router("/content", content_router, auth=bearer_auth, tags=["content"])
api.add_router("", learning_router, auth=bearer_auth, tags=["learning"])
api.add_router("/billing", billing_router, auth=bearer_auth, tags=["billing"])
api.add_router("/webhooks", webhooks_router, tags=["billing"])
