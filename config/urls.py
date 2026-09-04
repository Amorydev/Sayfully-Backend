from django.contrib import admin
from django.http import JsonResponse
from django.urls import path

from config.api import api


def health(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", api.urls),
    path("health/", health),
]
