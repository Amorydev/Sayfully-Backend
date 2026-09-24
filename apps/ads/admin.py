from django.contrib import admin

from . import models as m


@admin.register(m.AdPlacement)
class AdPlacementAdmin(admin.ModelAdmin):
    list_display = (
        "slot",
        "title_vi",
        "format",
        "reward_kind",
        "reward_source",
        "reward_reason",
        "reward_amount",
        "daily_cap",
        "cooldown_seconds",
        "is_enabled",
    )
    list_filter = ("is_enabled", "format", "reward_kind", "reward_source")
    list_editable = ("is_enabled", "daily_cap", "reward_amount")


@admin.register(m.AdImpression)
class AdImpressionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "slot",
        "status",
        "reward_kind",
        "granted_amount",
        "signature_verified",
        "created_at",
    )
    list_filter = ("status", "slot", "signature_verified")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "rewarded_at")
