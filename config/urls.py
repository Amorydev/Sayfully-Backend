from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import path

from config.api import api


def health(_request):
    """Readiness cho load balancer: kiểm kết nối DB. 503 nếu hỏng."""
    try:
        connection.ensure_connection()
        db_ok = True
    except Exception:  # noqa: BLE001 — health check nuốt mọi lỗi kết nối
        db_ok = False
    return JsonResponse(
        {"status": "ok" if db_ok else "degraded", "db": db_ok},
        status=200 if db_ok else 503,
    )


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", api.urls),
    path("health/", health),
]
