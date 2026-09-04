from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import RefreshToken, SocialAccount, User, UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    extra = 0


class SocialAccountInline(admin.TabularInline):
    model = SocialAccount
    extra = 0
    readonly_fields = ("provider", "provider_uid", "email", "created_at")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline, SocialAccountInline]
    list_display = ("email", "full_name", "is_active", "is_staff", "date_joined", "deleted_at")
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("email", "full_name")
    ordering = ("-date_joined",)
    readonly_fields = ("id", "date_joined", "last_login")
    fieldsets = (
        (None, {"fields": ("id", "email", "password")}),
        ("Thông tin", {"fields": ("full_name", "avatar_path")}),
        (
            "Quyền",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Mốc thời gian", {"fields": ("last_login", "date_joined", "deleted_at")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)


@admin.register(RefreshToken)
class RefreshTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "device_name", "created_at", "expires_at", "revoked_at")
    list_filter = ("revoked_at",)
    search_fields = ("user__email",)
    readonly_fields = ("id", "token_hash", "family_id", "created_at")

    def has_add_permission(self, request):
        return False


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "cefr_level",
        "xp_total",
        "level",
        "coins",
        "hearts",
        "streak_current",
        "is_premium",
    )
    list_filter = ("cefr_level", "is_premium", "accent")
    search_fields = ("user__email",)
