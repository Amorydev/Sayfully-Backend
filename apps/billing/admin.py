from django.contrib import admin

from . import models as m


@admin.register(m.Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "provider",
        "product_code",
        "status",
        "store",
        "started_at",
        "expires_at",
    )
    list_filter = ("provider", "status", "store")
    search_fields = ("user__email", "original_txn_id")
    raw_id_fields = ("user",)


@admin.register(m.PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "event_type", "event_id", "user", "processed_at", "created_at")
    list_filter = ("provider", "event_type")
    search_fields = ("event_id",)
    readonly_fields = ("payload",)


class RedemptionInline(admin.TabularInline):
    model = m.GiftCodeRedemption
    extra = 0
    raw_id_fields = ("user",)


@admin.register(m.GiftCode)
class GiftCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "days", "used_count", "max_uses", "expires_at", "is_active")
    inlines = [RedemptionInline]
