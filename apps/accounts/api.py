"""12 endpoint xác thực, phục vụ đồng thời mobile (Bearer) và web (cookie).

Đây là MẪU CHUẨN tài liệu hoá cho các app sau:
- mỗi endpoint có `summary` + `description`
- khai báo đủ mã lỗi, tất cả trỏ tới `ErrorOut`
- header `X-Client-Type` được khai báo để Swagger hiện ô nhập
"""

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django_ratelimit.decorators import ratelimit
from ninja import Header, Router

from apps.common.schemas import ErrorOut, MessageOut

from . import services
from .auth import (
    bearer_auth,
    clear_refresh_cookie,
    device_of,
    ip_of,
    is_web,
    read_refresh,
    set_refresh_cookie,
)
from .models import User
from .schemas import (
    AppleIn,
    AuthResultOut,
    ChangePasswordIn,
    ForgotPasswordIn,
    GoogleIn,
    LoginIn,
    MeOut,
    RefreshIn,
    RegisterIn,
    ResetPasswordIn,
    TokenOut,
)
from .social import verify_apple_identity_token, verify_google_id_token
from .tokens import revoke, revoke_all, rotate_refresh

router = Router()

RATE_AUTH = "5/m"  # chống dò mật khẩu / spam email

CLIENT_TYPE_DOC = Header(
    default="mobile",
    alias="X-Client-Type",
    description="`mobile` → refresh trong body · `web` → refresh trong httpOnly cookie",
)

E401 = "Token/thông tin đăng nhập không hợp lệ"
E422 = "Dữ liệu gửi lên không hợp lệ"
E429 = "Gửi quá nhiều yêu cầu"


def _tokens(
    request: HttpRequest, response: HttpResponse, access: str, refresh_raw: str
) -> TokenOut:
    """Web: refresh vào httpOnly cookie. Mobile: refresh trả trong body."""
    expires_in = settings.ACCESS_TOKEN_MINUTES * 60
    if is_web(request):
        set_refresh_cookie(response, refresh_raw)
        return TokenOut(access=access, refresh=None, expires_in=expires_in)
    return TokenOut(access=access, refresh=refresh_raw, expires_in=expires_in)


def _me(user: User) -> MeOut:
    profile = services.ensure_profile(user)
    return MeOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        avatar_path=user.avatar_path,
        date_joined=user.date_joined,
        profile=profile,
    )


# ------------------------------------------------------------------ đăng ký / đăng nhập
@router.post(
    "/register",
    response={200: TokenOut, 409: ErrorOut, 422: ErrorOut, 429: ErrorOut},
    auth=None,
    summary="Đăng ký bằng email",
    description=(
        "Tạo tài khoản mới và đăng nhập luôn. Mật khẩu tối thiểu 8 ký tự.\n\n"
        "Hồ sơ học tập (`UserProfile`) được tạo tự động ở trình độ **A1**.\n\n"
        "Lỗi thường gặp: `email_taken` (409)."
    ),
)
@ratelimit(key="ip", rate=RATE_AUTH, method="POST", block=True)
def register(
    request, data: RegisterIn, response: HttpResponse, x_client_type: str = CLIENT_TYPE_DOC
):
    user = services.register_user(data.email, data.password, data.full_name)
    access, refresh_raw = services.start_session(
        user, device_name=device_of(request), ip=ip_of(request)
    )
    return _tokens(request, response, access, refresh_raw)


@router.post(
    "/token",
    response={200: TokenOut, 401: ErrorOut, 422: ErrorOut, 429: ErrorOut},
    auth=None,
    summary="Đăng nhập bằng email",
    description=(
        "Trả về cặp access + refresh token.\n\n"
        "Thông báo lỗi cố ý mơ hồ (`invalid_credentials`) để không tiết lộ "
        "email nào đang tồn tại."
    ),
)
@ratelimit(key="ip", rate=RATE_AUTH, method="POST", block=True)
def login(request, data: LoginIn, response: HttpResponse, x_client_type: str = CLIENT_TYPE_DOC):
    user = services.authenticate_password(data.email, data.password)
    access, refresh_raw = services.start_session(
        user, device_name=device_of(request), ip=ip_of(request)
    )
    return _tokens(request, response, access, refresh_raw)


@router.post(
    "/refresh",
    response={200: TokenOut, 401: ErrorOut},
    auth=None,
    summary="Xoay refresh token",
    description=(
        "Cấp cặp token mới và **thu hồi token cũ** (xoay vòng).\n\n"
        "- `mobile`: gửi `refresh` trong body\n"
        "- `web`: bỏ trống body, token đọc từ cookie\n\n"
        "⚠️ Nếu gửi một token **đã bị thu hồi**, hệ thống coi như token bị đánh cắp "
        "và thu hồi toàn bộ phiên của lần đăng nhập đó (`refresh_reused`)."
    ),
)
def refresh_token(
    request, data: RefreshIn, response: HttpResponse, x_client_type: str = CLIENT_TYPE_DOC
):
    raw = read_refresh(request, data.refresh)
    _user, access, new_raw = rotate_refresh(raw, device_name=device_of(request), ip=ip_of(request))
    return _tokens(request, response, access, new_raw)


# ------------------------------------------------------------------ social
@router.post(
    "/google",
    response={200: AuthResultOut, 401: ErrorOut, 422: ErrorOut, 500: ErrorOut},
    auth=None,
    summary="Đăng nhập Google",
    description=(
        "Nhận `id_token` từ Google Sign-In trên client.\n\n"
        "⚠️ Server chấp nhận **3 client ID khác nhau** (Android / iOS / Web) — "
        "phải khai báo đủ cả ba trong biến môi trường, nếu không sẽ nhận "
        "`google_bad_audience`.\n\n"
        "`created = true` nghĩa là tài khoản vừa được tạo mới."
    ),
)
def login_google(
    request, data: GoogleIn, response: HttpResponse, x_client_type: str = CLIENT_TYPE_DOC
):
    profile = verify_google_id_token(data.id_token)
    user, created = services.login_or_create_social(profile)
    access, refresh_raw = services.start_session(
        user, device_name=device_of(request), ip=ip_of(request)
    )
    return AuthResultOut(tokens=_tokens(request, response, access, refresh_raw), created=created)


@router.post(
    "/apple",
    response={200: AuthResultOut, 401: ErrorOut, 422: ErrorOut, 503: ErrorOut},
    auth=None,
    summary="Đăng nhập Apple",
    description=(
        "Nhận `identity_token` từ Sign in with Apple.\n\n"
        "⚠️ Apple **chỉ trả email và tên ở lần đăng nhập đầu tiên**. Client bắt buộc "
        "gửi kèm `full_name` ở lần đó, vì các lần sau Apple sẽ không gửi lại nữa.\n\n"
        "Nếu người dùng ẩn email, Apple trả email dạng `@privaterelay.appleid.com`; "
        "trường hợp không có email, hệ thống tự sinh email nội bộ."
    ),
)
def login_apple(
    request, data: AppleIn, response: HttpResponse, x_client_type: str = CLIENT_TYPE_DOC
):
    profile = verify_apple_identity_token(data.identity_token)
    if data.full_name:
        profile = type(profile)(**{**profile.__dict__, "full_name": data.full_name})
    user, created = services.login_or_create_social(profile)
    if data.full_name and not user.full_name:
        user.full_name = data.full_name
        user.save(update_fields=["full_name"])
    access, refresh_raw = services.start_session(
        user, device_name=device_of(request), ip=ip_of(request)
    )
    return AuthResultOut(tokens=_tokens(request, response, access, refresh_raw), created=created)


# ------------------------------------------------------------------ phiên
@router.get(
    "/me",
    response={200: MeOut, 401: ErrorOut},
    auth=bearer_auth,
    summary="Hồ sơ người dùng hiện tại",
    description="Trả về thông tin tài khoản kèm hồ sơ học tập (XP, streak, tim, xu, Premium).",
)
def me(request):
    return _me(request.auth)


@router.post(
    "/logout",
    response={200: MessageOut},
    auth=None,
    summary="Đăng xuất thiết bị hiện tại",
    description=(
        "Thu hồi refresh token hiện tại và xoá cookie (nếu là web).\n\n"
        "Luôn trả `200` kể cả khi token đã hết hạn — đăng xuất không nên báo lỗi cho người dùng."
    ),
)
def logout(request, data: RefreshIn, response: HttpResponse, x_client_type: str = CLIENT_TYPE_DOC):
    try:
        revoke(read_refresh(request, data.refresh))
    except Exception:
        pass
    if is_web(request):
        clear_refresh_cookie(response)
    return MessageOut(message="Đã đăng xuất")


@router.post(
    "/logout-all",
    response={200: MessageOut, 401: ErrorOut},
    auth=bearer_auth,
    summary="Đăng xuất khỏi mọi thiết bị",
    description="Thu hồi toàn bộ refresh token của tài khoản. Dùng khi nghi ngờ bị lộ tài khoản.",
)
def logout_all(request, response: HttpResponse, x_client_type: str = CLIENT_TYPE_DOC):
    revoke_all(request.auth)
    if is_web(request):
        clear_refresh_cookie(response)
    return MessageOut(message="Đã đăng xuất khỏi tất cả thiết bị")


# ------------------------------------------------------------------ mật khẩu
@router.post(
    "/password/forgot",
    response={200: MessageOut, 422: ErrorOut, 429: ErrorOut},
    auth=None,
    summary="Quên mật khẩu",
    description=(
        "Gửi email chứa liên kết đặt lại mật khẩu, **hết hạn sau 30 phút**.\n\n"
        "Luôn trả về cùng một thông điệp dù email có tồn tại hay không, "
        "để không cho phép dò xem email nào đã đăng ký."
    ),
)
@ratelimit(key="ip", rate=RATE_AUTH, method="POST", block=True)
def forgot_password(request, data: ForgotPasswordIn):
    services.request_password_reset(data.email)
    return MessageOut(message="Nếu email tồn tại, chúng tôi đã gửi hướng dẫn đặt lại mật khẩu")


@router.post(
    "/password/reset",
    response={200: MessageOut, 400: ErrorOut, 422: ErrorOut},
    auth=None,
    summary="Đặt lại mật khẩu",
    description=(
        "Dùng `uid` và `token` lấy từ liên kết trong email.\n\n"
        "Token chỉ dùng được **một lần** và hết hạn sau 30 phút. "
        "Sau khi đổi, mọi phiên đăng nhập cũ đều bị thu hồi."
    ),
)
def reset_password(request, data: ResetPasswordIn):
    services.confirm_password_reset(data.uid, data.token, data.new_password)
    return MessageOut(message="Đặt lại mật khẩu thành công, vui lòng đăng nhập lại")


@router.post(
    "/change-password",
    response={200: MessageOut, 401: ErrorOut, 422: ErrorOut},
    auth=bearer_auth,
    summary="Đổi mật khẩu",
    description=(
        "Đổi mật khẩu khi đã đăng nhập. **Thu hồi toàn bộ phiên** sau khi đổi.\n\n"
        "Tài khoản chỉ đăng nhập bằng Google/Apple (chưa có mật khẩu) "
        "có thể để trống `old_password` để đặt mật khẩu lần đầu."
    ),
)
def change_password(
    request, data: ChangePasswordIn, response: HttpResponse, x_client_type: str = CLIENT_TYPE_DOC
):
    services.change_password(request.auth, data.old_password, data.new_password)
    if is_web(request):
        clear_refresh_cookie(response)
    return MessageOut(message="Đổi mật khẩu thành công, vui lòng đăng nhập lại")


# ------------------------------------------------------------------ xoá tài khoản
@router.delete(
    "/delete-account",
    response={200: MessageOut, 401: ErrorOut},
    auth=bearer_auth,
    summary="Xoá tài khoản",
    description=(
        "Ẩn danh thông tin cá nhân **ngay lập tức** và vô hiệu hoá tài khoản; "
        "dữ liệu bị xoá cứng sau **30 ngày**.\n\n"
        "Email được giải phóng ngay nên người dùng có thể đăng ký lại bằng email cũ."
    ),
)
def delete_account(request, response: HttpResponse, x_client_type: str = CLIENT_TYPE_DOC):
    services.soft_delete_account(request.auth)
    if is_web(request):
        clear_refresh_cookie(response)
    return MessageOut(message="Tài khoản đã bị vô hiệu hoá và sẽ được xoá sau 30 ngày")
