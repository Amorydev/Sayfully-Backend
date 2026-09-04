"""Schema dùng chung."""

from ninja import Schema


class ErrorDetail(Schema):
    """Một lỗi. ``details`` chỉ có nội dung ở 422: ``{"email": ["Email không hợp lệ"]}``."""

    code: str
    message: str
    details: dict[str, list[str]] = {}


class ErrorOut(Schema):
    error: ErrorDetail


class MessageOut(Schema):
    message: str
