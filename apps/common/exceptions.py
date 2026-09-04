"""Lỗi nghiệp vụ + mọi handler để TOÀN BỘ lỗi dưới ``/api/`` trả cùng một hình dạng.

    {"error": {"code": "...", "message": "...", "details": {...}}}

- ``code``    : hợp đồng với client (client phân nhánh trên trường này). Không đổi tuỳ tiện.
- ``message`` : tiếng Việt, để hiển thị. Có thể đổi câu chữ bất kỳ lúc nào.
- ``details`` : CHỈ có nội dung ở 422 — map ``field -> [lỗi, ...]``. Các mã khác luôn ``{}``.

Đường đi của lỗi:
1. Lỗi trong endpoint → Ninja tra handler theo MRO → :func:`register_exception_handlers`.
2. Lỗi không đi qua Ninja (405 text, 404 route lạ, 400 DisallowedHost, 500 của Django)
   → :class:`apps.common.middleware.ApiErrorEnvelopeMiddleware` bọc lại.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from django.conf import settings
from django.http import Http404, HttpRequest, JsonResponse
from django_ratelimit.exceptions import Ratelimited
from ninja.errors import AuthenticationError, HttpError, ValidationError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lỗi nghiệp vụ (raise trong service/endpoint)
# ---------------------------------------------------------------------------
class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict | None = None,
    ):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "bad_gateway",
    503: "service_unavailable",
    504: "gateway_timeout",
}
HTTP_MESSAGES = {
    400: "Yêu cầu không hợp lệ",
    401: "Cần đăng nhập",
    403: "Bạn không có quyền thực hiện thao tác này",
    404: "Không tìm thấy tài nguyên",
    405: "Phương thức không được hỗ trợ",
    409: "Xung đột dữ liệu",
    413: "Nội dung gửi lên quá lớn",
    415: "Định dạng nội dung không được hỗ trợ",
    422: "Dữ liệu không hợp lệ",
    429: "Bạn thao tác quá nhanh, vui lòng thử lại sau",
    500: "Lỗi hệ thống, vui lòng thử lại sau",
    502: "Máy chủ trung gian gặp lỗi",
    503: "Dịch vụ tạm thời không sẵn sàng",
    504: "Máy chủ phản hồi quá lâu",
}


def code_for(status: int) -> str:
    return HTTP_CODES.get(status, f"http_{status}")


def message_for(status: int) -> str:
    return HTTP_MESSAGES.get(status, f"Lỗi HTTP {status}")


def error_response(
    status: int, code: str, message: str, details: dict | None = None
) -> JsonResponse:
    """Điểm duy nhất tạo phản hồi lỗi — mọi handler và middleware đều đi qua đây."""
    return JsonResponse(
        {"error": {"code": code, "message": message, "details": details or {}}},
        status=status,
    )


# ---------------------------------------------------------------------------
# 422: dịch lỗi pydantic sang tiếng Việt và gom theo field
# ---------------------------------------------------------------------------
_SOURCES = {"body", "query", "path", "header", "cookie", "form", "file"}


def _field_of(loc: Iterable) -> str:
    """``["body", "data", "email"]`` → ``"email"``; ``["query", "limit"]`` → ``"limit"``;
    ``["body", "data", "answers", 0, "rating"]`` → ``"answers.0.rating"``."""
    parts = [str(p) for p in loc]
    if parts and parts[0] in _SOURCES:
        source = parts.pop(0)
        if source in ("body", "form") and parts:
            parts.pop(0)  # bỏ tên tham số bọc ngoài (thường là "data")
    return ".".join(parts) or "__all__"


def _translate(err: dict) -> str:
    kind = err.get("type", "")
    ctx = err.get("ctx") or {}
    msg = str(err.get("msg") or "")
    match kind:
        case "missing":
            return "Trường này là bắt buộc"
        case "string_too_short":
            return f"Tối thiểu {ctx.get('min_length')} ký tự"
        case "string_too_long":
            return f"Tối đa {ctx.get('max_length')} ký tự"
        case "too_short":
            return f"Cần ít nhất {ctx.get('min_length')} phần tử"
        case "too_long":
            return f"Tối đa {ctx.get('max_length')} phần tử"
        case "int_parsing" | "int_type" | "float_parsing" | "float_type" | "int_from_float":
            return "Phải là số"
        case "bool_parsing" | "bool_type":
            return "Phải là true hoặc false"
        case "string_type":
            return "Phải là chuỗi"
        case "list_type":
            return "Phải là danh sách"
        case "dict_type" | "model_type" | "model_attributes_type":
            return "Phải là đối tượng"
        case "greater_than_equal":
            return f"Phải lớn hơn hoặc bằng {ctx.get('ge')}"
        case "greater_than":
            return f"Phải lớn hơn {ctx.get('gt')}"
        case "less_than_equal":
            return f"Phải nhỏ hơn hoặc bằng {ctx.get('le')}"
        case "less_than":
            return f"Phải nhỏ hơn {ctx.get('lt')}"
        case "enum" | "literal_error":
            return "Giá trị không nằm trong danh sách cho phép"
        case "uuid_parsing" | "uuid_type":
            return "Không phải UUID hợp lệ"
        case "date_parsing" | "date_type" | "datetime_parsing" | "datetime_type":
            return "Ngày giờ không hợp lệ"
        case "json_invalid":
            return "JSON không hợp lệ"
        case "string_pattern_mismatch":
            return "Định dạng không hợp lệ"
        case "value_error":
            if "email" in msg.lower():
                return "Email không hợp lệ"
            return msg.removeprefix("Value error, ") or "Giá trị không hợp lệ"
    return msg or "Giá trị không hợp lệ"


def group_validation_errors(errors: list[dict]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for err in errors:
        grouped.setdefault(_field_of(err.get("loc", ())), []).append(_translate(err))
    return grouped


# ---------------------------------------------------------------------------
# Handler cho Ninja (chữ ký: request, exc)
# ---------------------------------------------------------------------------
def app_error_handler(request: HttpRequest, exc: AppError) -> JsonResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


def validation_error_handler(request: HttpRequest, exc: ValidationError) -> JsonResponse:
    return error_response(
        422, "validation_error", message_for(422), group_validation_errors(exc.errors)
    )


def authentication_error_handler(request: HttpRequest, exc: AuthenticationError) -> JsonResponse:
    # Chỉ tới đây khi header Authorization thiếu hoặc sai định dạng;
    # token sai/hết hạn đã được BearerAuth raise Unauthorized với code cụ thể.
    return error_response(401, "token_missing", "Thiếu hoặc sai định dạng header Authorization")


def http_error_handler(request: HttpRequest, exc: HttpError) -> JsonResponse:
    status = exc.status_code
    message = message_for(status)
    if status == 400 and "parse" in str(exc).lower():
        message = "Không đọc được nội dung yêu cầu, kiểm tra lại JSON"
    return error_response(status, code_for(status), message)


def http404_handler(request: HttpRequest, exc: Http404) -> JsonResponse:
    return error_response(404, "not_found", message_for(404))


def ratelimited_handler(request: HttpRequest, exc: Ratelimited) -> JsonResponse:
    return error_response(429, "rate_limited", message_for(429))


def unhandled_exception_handler(request: HttpRequest, exc: Exception) -> JsonResponse:
    logger.exception("Lỗi chưa xử lý tại %s %s", request.method, request.path)
    message = f"{type(exc).__name__}: {exc}" if settings.DEBUG else message_for(500)
    return error_response(500, "internal_error", message)


def register_exception_handlers(api) -> None:
    """Gọi một lần trong ``config/api.py``. Ninja chọn handler theo MRO nên thứ tự
    khai báo không quan trọng, nhưng phải có đủ từ cụ thể tới tổng quát."""
    api.add_exception_handler(AppError, app_error_handler)
    api.add_exception_handler(ValidationError, validation_error_handler)
    api.add_exception_handler(AuthenticationError, authentication_error_handler)
    api.add_exception_handler(HttpError, http_error_handler)
    api.add_exception_handler(Http404, http404_handler)
    api.add_exception_handler(Ratelimited, ratelimited_handler)
    api.add_exception_handler(Exception, unhandled_exception_handler)
