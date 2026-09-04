from django.contrib import admin

from . import models as m


@admin.register(m.RoleplayScenario)
class RoleplayScenarioAdmin(admin.ModelAdmin):
    list_display = ("title_vi", "level", "topic", "is_premium")
    list_filter = ("level", "topic", "is_premium")


class AIMessageInline(admin.TabularInline):
    model = m.AIMessage
    extra = 0
    readonly_fields = ("role", "content", "tokens_in", "tokens_out", "created_at")


@admin.register(m.AIConversation)
class AIConversationAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "scenario", "created_at", "ended_at")
    list_filter = ("kind",)
    raw_id_fields = ("user",)
    inlines = [AIMessageInline]


@admin.register(m.AIQuota)
class AIQuotaAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "messages_used", "tokens_used")
    raw_id_fields = ("user",)
