"""Tầng token: cấp, giải mã, và các trường hợp token hỏng."""
import uuid
from datetime import timedelta

import jwt
import pytest
import time_machine
from django.conf import settings
from django.utils import timezone

from apps.accounts.tokens import decode_access, issue_access, issue_refresh
from apps.common.exceptions import Unauthorized

pytestmark = pytest.mark.django_db


def test_access_token_giai_ma_dung_user(user):
    assert decode_access(issue_access(user)) == user.id


def test_access_token_het_han_bi_tu_choi(user):
    token = issue_access(user)
    later = timezone.now() + timedelta(minutes=settings.ACCESS_TOKEN_MINUTES + 1)
    with time_machine.travel(later), pytest.raises(Unauthorized) as exc:
        decode_access(token)
    assert exc.value.code == "token_expired"


def test_chu_ky_sai_bi_tu_choi(user):
    gia_mao = jwt.encode(
        {"sub": str(user.id), "typ": "access",
         "exp": int((timezone.now() + timedelta(minutes=5)).timestamp())},
        "khoa-sai", algorithm="HS256",
    )
    with pytest.raises(Unauthorized) as exc:
        decode_access(gia_mao)
    assert exc.value.code == "token_invalid"


def test_refresh_khong_dung_duoc_nhu_access(user):
    """Bảo vệ then chốt: refresh token không được coi là access token."""
    raw, _ = issue_refresh(user)
    with pytest.raises(Unauthorized):
        decode_access(raw)


def test_token_sai_loai_bi_tu_choi(user):
    sai_loai = jwt.encode(
        {"sub": str(user.id), "typ": "refresh",
         "exp": int((timezone.now() + timedelta(minutes=5)).timestamp())},
        settings.JWT_SIGNING_KEY, algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(Unauthorized) as exc:
        decode_access(sai_loai)
    assert exc.value.code == "token_wrong_type"


def test_refresh_luu_hash_khong_luu_ban_goc(user):
    raw, obj = issue_refresh(user)
    assert obj.token_hash != raw
    assert len(obj.token_hash) == 64          # sha256 hex
    assert obj.family_id is not None
    assert isinstance(obj.family_id, uuid.UUID)
