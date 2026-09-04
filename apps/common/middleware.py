"""Lưới an toàn cho hợp đồng lỗi: phản hồi lỗi dưới ``/api/`` mà không phải JSON → bọc envelope.

Bắt những đường KHÔNG đi qua handler của Ninja:
- 405: ``PathView._not_allowed`` trả text ``Method not allowed`` thẳng
- 404: route không khớp → Django ``handler404`` trả HTML
- 400: ``DisallowedHost`` nổ trong CommonMiddleware
- 500: lỗi ngoài tầm Ninja (middleware khác, URL resolver)

Đặt ĐẦU danh sách MIDDLEWARE để đứng ngoài cùng và thấy phản hồi cuối cùng.
Không đụng tới ``/api/v1/docs`` hay openapi.json (đều là 200).
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponseBase

from apps.common.exceptions import code_for, error_response, message_for

API_PREFIX = "/api/"


class ApiErrorEnvelopeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        response = self.get_response(request)
        if not request.path.startswith(API_PREFIX) or response.status_code < 400:
            return response
        if response.get("Content-Type", "").startswith("application/json"):
            return response  # đã đúng hình dạng (từ handler của Ninja)
        status = response.status_code
        wrapped = error_response(status, code_for(status), message_for(status))
        if status == 405 and response.has_header("Allow"):
            wrapped["Allow"] = response["Allow"]
        return wrapped
