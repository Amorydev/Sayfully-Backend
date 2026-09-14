"""Schema vào/ra cho nhóm endpoint auth."""

from datetime import datetime
from uuid import UUID

from ninja import Schema
from pydantic import EmailStr, Field


# ---------------------------------------------------------------- input
class RegisterIn(Schema):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = ""


class LoginIn(Schema):
    email: EmailStr
    password: str


class RefreshIn(Schema):
    # Mobile gửi trong body; web bỏ trống vì token nằm trong httpOnly cookie.
    refresh: str | None = None


class GoogleIn(Schema):
    id_token: str


class AppleIn(Schema):
    identity_token: str
    # Apple CHỈ trả tên ở lần đăng nhập đầu; client phải chuyển tiếp cho server.
    full_name: str = ""


class ForgotPasswordIn(Schema):
    email: EmailStr


class ResetPasswordIn(Schema):
    uid: str
    token: str
    new_password: str = Field(min_length=8)


class ChangePasswordIn(Schema):
    old_password: str = ""  # rỗng với tài khoản chỉ đăng nhập bằng social
    new_password: str = Field(min_length=8)


# ---------------------------------------------------------------- output
class TokenOut(Schema):
    access: str
    refresh: str | None = None  # null khi client là web (nằm trong cookie)
    token_type: str = "Bearer"
    expires_in: int  # giây


class ProfileOut(Schema):
    cefr_level: str
    goal_level: str
    learning_goal: str
    onboarding_completed: bool
    onboarding_completed_at: datetime | None = None
    xp_total: int
    level: int
    coins: int
    hearts: int
    streak_current: int
    streak_best: int
    streak_freezes: int
    accent: str
    show_ipa: bool
    daily_goal_xp: int
    daily_goal_words: int
    timezone: str
    ui_language: str
    reminder_enabled: bool
    reminder_time: str  # "HH:MM"
    streak_reminder: bool
    event_notifications: bool
    is_premium: bool
    premium_until: datetime | None = None
    xp_boost_until: datetime | None = None
    avatar_frame: str = ""
    avatar_frame_colors: list[str] = []

    @staticmethod
    def resolve_reminder_time(obj) -> str:
        return obj.reminder_time.strftime("%H:%M")

    @staticmethod
    def resolve_avatar_frame_colors(obj) -> list[str]:
        from apps.gamification.shop import frame_colors  # noqa: PLC0415 — tránh import vòng

        return frame_colors(getattr(obj, "avatar_frame", ""))


class MeOut(Schema):
    id: UUID
    email: str
    full_name: str
    avatar_path: str
    date_joined: datetime
    profile: ProfileOut


class AuthResultOut(Schema):
    """Trả về sau đăng nhập social — báo cho client biết có phải tài khoản mới."""

    tokens: TokenOut
    created: bool
