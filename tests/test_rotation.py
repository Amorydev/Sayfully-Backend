"""Xoay vòng refresh token + phát hiện token bị đánh cắp."""
import pytest

from apps.accounts.models import RefreshToken
from apps.accounts.tokens import issue_refresh, revoke_all, rotate_refresh
from apps.common.exceptions import Unauthorized

pytestmark = pytest.mark.django_db


def test_xoay_vong_thu_hoi_token_cu(user):
    raw, obj = issue_refresh(user)
    _u, _access, raw_moi = rotate_refresh(raw)

    obj.refresh_from_db()
    assert obj.revoked_at is not None, "token cũ phải bị thu hồi"
    assert raw_moi != raw


def test_token_moi_cung_family_voi_token_cu(user):
    raw, obj = issue_refresh(user)
    rotate_refresh(raw)
    moi = RefreshToken.objects.exclude(pk=obj.pk).get(user=user)
    assert moi.family_id == obj.family_id


def test_dung_lai_token_da_thu_hoi_se_giet_ca_family(user):
    """Đây là bảo vệ quan trọng nhất: token bị đánh cắp không dùng được lâu."""
    raw, _ = issue_refresh(user)
    _u, _a, raw_moi = rotate_refresh(raw)          # kẻ tấn công hoặc user xoay 1 lần

    with pytest.raises(Unauthorized) as exc:
        rotate_refresh(raw)                        # dùng lại token cũ
    assert exc.value.code == "refresh_reused"

    # Token mới nhất cũng phải chết theo, buộc đăng nhập lại
    with pytest.raises(Unauthorized):
        rotate_refresh(raw_moi)

    assert not RefreshToken.objects.filter(user=user, revoked_at__isnull=True).exists()


def test_token_khong_ton_tai_bi_tu_choi(db):
    with pytest.raises(Unauthorized) as exc:
        rotate_refresh("token-bia-dat")
    assert exc.value.code == "refresh_invalid"


def test_tai_khoan_bi_vo_hieu_khong_xoay_duoc(user):
    raw, _ = issue_refresh(user)
    user.is_active = False
    user.save(update_fields=["is_active"])
    with pytest.raises(Unauthorized) as exc:
        rotate_refresh(raw)
    assert exc.value.code == "account_inactive"


def test_revoke_all_thu_hoi_moi_thiet_bi(user):
    raw1, _ = issue_refresh(user, device_name="iPhone")
    raw2, _ = issue_refresh(user, device_name="Chrome")
    assert revoke_all(user) == 2
    for raw in (raw1, raw2):
        with pytest.raises(Unauthorized):
            rotate_refresh(raw)
