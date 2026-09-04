"""Xác thực Google/Apple — mock hoàn toàn, không gọi mạng."""
import pytest

from apps.accounts import social
from apps.accounts.services import login_or_create_social
from apps.accounts.social import SocialProfile, verify_google_id_token
from apps.common.exceptions import Unauthorized

pytestmark = pytest.mark.django_db

CLIENT_ID_ANDROID = "111.apps.googleusercontent.com"
CLIENT_ID_WEB = "222.apps.googleusercontent.com"


@pytest.fixture
def google_ids(settings):
    settings.GOOGLE_CLIENT_IDS = [CLIENT_ID_ANDROID, CLIENT_ID_WEB]
    return settings.GOOGLE_CLIENT_IDS


def _fake_google(monkeypatch, payload):
    monkeypatch.setattr(
        social.google_id_token, "verify_oauth2_token", lambda *a, **kw: payload
    )


def test_google_hop_le(monkeypatch, google_ids):
    _fake_google(monkeypatch, {
        "iss": "https://accounts.google.com", "aud": CLIENT_ID_ANDROID,
        "sub": "google-uid-1", "email": "a@example.com",
        "email_verified": True, "name": "Nguyễn A",
    })
    p = verify_google_id_token("token-gia")
    assert p.provider == "google" and p.uid == "google-uid-1"
    assert p.email == "a@example.com" and p.email_verified is True


def test_google_sai_audience_bi_tu_choi(monkeypatch, google_ids):
    """Bẫy hay gặp: token phát cho ứng dụng KHÁC vẫn hợp lệ về chữ ký."""
    _fake_google(monkeypatch, {
        "iss": "https://accounts.google.com", "aud": "999.apps.googleusercontent.com",
        "sub": "google-uid-2",
    })
    with pytest.raises(Unauthorized) as exc:
        verify_google_id_token("token-gia")
    assert exc.value.code == "google_bad_audience"


def test_google_sai_issuer_bi_tu_choi(monkeypatch, google_ids):
    _fake_google(monkeypatch, {
        "iss": "https://ke-gia-mao.com", "aud": CLIENT_ID_ANDROID, "sub": "x",
    })
    with pytest.raises(Unauthorized) as exc:
        verify_google_id_token("token-gia")
    assert exc.value.code == "google_bad_issuer"


def test_google_chap_nhan_ca_3_client_id(monkeypatch, google_ids):
    """Android, iOS, Web có client ID khác nhau — phải chấp nhận tất cả."""
    for aud in (CLIENT_ID_ANDROID, CLIENT_ID_WEB):
        _fake_google(monkeypatch, {
            "iss": "accounts.google.com", "aud": aud, "sub": f"uid-{aud}",
        })
        assert verify_google_id_token("t").uid == f"uid-{aud}"


# ------------------------------------------------------------------ liên kết
def test_lan_dau_tao_user_moi(db):
    p = SocialProfile(provider="google", uid="u1", email="moi@example.com",
                      full_name="Người Mới")
    user, created = login_or_create_social(p)
    assert created is True and user.email == "moi@example.com"


def test_lan_hai_dung_lai_user_cu(db):
    p = SocialProfile(provider="google", uid="u1", email="moi@example.com")
    user1, created1 = login_or_create_social(p)
    user2, created2 = login_or_create_social(p)
    assert created1 is True and created2 is False and user1.pk == user2.pk


def test_gan_vao_tai_khoan_email_da_co(user):
    p = SocialProfile(provider="google", uid="u9", email=user.email)
    linked, created = login_or_create_social(p)
    assert created is False and linked.pk == user.pk


def test_apple_khong_co_email_van_tao_duoc(db):
    """Apple có thể không trả email — vẫn phải đăng nhập được."""
    p = SocialProfile(provider="apple", uid="apple-uid-1", email="")
    user, created = login_or_create_social(p)
    assert created is True
    assert user.email.endswith("@users.noreply.sayfully.com")


def test_apple_bo_sung_email_o_lan_sau(db):
    """Apple chỉ gửi email lần đầu; nếu lần sau có thì phải lưu bổ sung."""
    login_or_create_social(SocialProfile(provider="apple", uid="a1", email=""))
    user, _ = login_or_create_social(
        SocialProfile(provider="apple", uid="a1", email="sau@example.com")
    )
    assert user.social_accounts.get(provider="apple").email == "sau@example.com"


# ------------------------------------------------------------------ Apple
# Ký bằng RSA thật rồi verify — không mock jwt.decode, để thật sự kiểm chữ ký.
import time  # noqa: E402

import jwt as pyjwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from apps.accounts.social import verify_apple_identity_token  # noqa: E402

BUNDLE_ID = "com.sayfully.app"


@pytest.fixture(scope="module")
def apple_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def apple_env(settings, monkeypatch, apple_key):
    settings.APPLE_AUDIENCES = [BUNDLE_ID, "com.sayfully.web"]

    class _Key:
        key = apple_key.public_key()

    monkeypatch.setattr(social._apple_jwks, "get_signing_key_from_jwt", lambda _t: _Key())
    return settings


def _apple_token(key, **claims):
    now = int(time.time())
    payload = {
        "iss": "https://appleid.apple.com", "aud": BUNDLE_ID, "sub": "apple-uid-9",
        "iat": now, "exp": now + 600,
    }
    payload.update(claims)
    return pyjwt.encode(payload, key, algorithm="RS256")


def test_apple_token_hop_le(apple_env, apple_key):
    token = _apple_token(apple_key, email="abc@privaterelay.appleid.com",
                         email_verified="true")
    p = verify_apple_identity_token(token)
    assert p.provider == "apple" and p.uid == "apple-uid-9"
    assert p.email_verified is True


def test_apple_sai_audience_bi_tu_choi(apple_env, apple_key):
    token = _apple_token(apple_key, aud="com.ke-khac.app")
    with pytest.raises(Unauthorized) as exc:
        verify_apple_identity_token(token)
    assert exc.value.code == "apple_bad_audience"


def test_apple_het_han_bi_tu_choi(apple_env, apple_key):
    now = int(time.time())
    token = _apple_token(apple_key, iat=now - 1200, exp=now - 600)
    with pytest.raises(Unauthorized) as exc:
        verify_apple_identity_token(token)
    assert exc.value.code == "apple_expired"


def test_apple_sai_issuer_bi_tu_choi(apple_env, apple_key):
    token = _apple_token(apple_key, iss="https://ke-gia-mao.com")
    with pytest.raises(Unauthorized) as exc:
        verify_apple_identity_token(token)
    assert exc.value.code == "apple_invalid"
