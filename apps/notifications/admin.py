from django.contrib import admin

from . import models as m


@admin.register(m.Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "platform", "app_version", "is_active", "last_seen_at")
    list_filter = ("platform", "is_active")
    raw_id_fields = ("user",)


@admin.register(m.Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "title_vi", "read_at", "created_at")
    list_filter = ("kind",)
    raw_id_fields = ("user",)
