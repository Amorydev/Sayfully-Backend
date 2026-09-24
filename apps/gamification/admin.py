from django.contrib import admin

from . import models as m


@admin.register(m.Challenge)
class ChallengeAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "scope",
        "metric",
        "title_vi",
        "target",
        "reward_xp",
        "reward_coins",
        "is_active",
    )
    list_filter = ("scope", "metric", "is_active")


@admin.register(m.UserChallenge)
class UserChallengeAdmin(admin.ModelAdmin):
    list_display = ("user", "challenge", "period_key", "progress", "completed_at", "claimed_at")
    raw_id_fields = ("user",)


@admin.register(m.Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ("code", "title_vi", "order")


@admin.register(m.UserBadge)
class UserBadgeAdmin(admin.ModelAdmin):
    list_display = ("user", "badge", "unlocked_at")
    raw_id_fields = ("user",)


class LeagueMembershipInline(admin.TabularInline):
    model = m.LeagueMembership
    extra = 0
    raw_id_fields = ("user",)


@admin.register(m.LeagueGroup)
class LeagueGroupAdmin(admin.ModelAdmin):
    list_display = ("tier", "iso_year", "iso_week", "created_at")
    list_filter = ("tier",)
    inlines = [LeagueMembershipInline]


@admin.register(m.ShopItem)
class ShopItemAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "title_vi",
        "category",
        "cost_coins",
        "discount_pct",
        "sale_until",
        "order",
        "is_active",
    )
    list_filter = ("category", "is_active")


@admin.register(m.ShopReceipt)
class ShopReceiptAdmin(admin.ModelAdmin):
    list_display = ("user", "item", "coins_spent", "balance_after", "created_at")
    raw_id_fields = ("user",)


@admin.register(m.UserCosmetic)
class UserCosmeticAdmin(admin.ModelAdmin):
    list_display = ("user", "item", "acquired_at")
    raw_id_fields = ("user",)


@admin.register(m.ShopWishlist)
class ShopWishlistAdmin(admin.ModelAdmin):
    list_display = ("user", "item", "notified_at", "created_at")
    raw_id_fields = ("user",)


@admin.register(m.CoinTransaction)
class CoinTransactionAdmin(admin.ModelAdmin):
    list_display = ("user", "amount", "reason", "balance_after", "created_at")
    list_filter = ("reason",)
    raw_id_fields = ("user",)


@admin.register(m.Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("code", "title_vi", "kind", "min_level", "is_featured", "is_active", "order")
    list_filter = ("kind", "is_featured", "is_active")


@admin.register(m.GameScore)
class GameScoreAdmin(admin.ModelAdmin):
    list_display = ("user", "game", "level", "score", "accuracy", "coins_earned", "played_at")
    list_filter = ("game", "level")
    raw_id_fields = ("user",)


class MatchPairsWordInline(admin.TabularInline):
    model = m.MatchPairsWord
    extra = 0


@admin.register(m.MatchPairsStage)
class MatchPairsStageAdmin(admin.ModelAdmin):
    list_display = ("order", "code", "title_vi", "pair_count", "level", "is_active")
    list_filter = ("level", "is_active")
    search_fields = ("code", "title_vi")
    inlines = [MatchPairsWordInline]

    def get_queryset(self, request):
        return super().get_queryset(request).with_pair_count()

    @admin.display(description="Cặp", ordering="pair_count")
    def pair_count(self, obj):
        n = obj.pair_count
        return n if n >= m.MatchPairsStage.MIN_PAIRS else f"{n} ⚠"


@admin.register(m.MatchPairsProgress)
class MatchPairsProgressAdmin(admin.ModelAdmin):
    list_display = ("user", "stage", "difficulty", "stars", "best_moves", "play_count")
    list_filter = ("difficulty", "stars")
    raw_id_fields = ("user",)
