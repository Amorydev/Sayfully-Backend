"""Quảng cáo: cấu hình, vé, trần ngày/xu, cộng thưởng qua SSV."""

from datetime import date, timedelta

import pytest
from django.utils import timezone as djtz

from apps.accounts.services import ensure_profile
from apps.ads.management.commands.seed_ads import seed_ads
from apps.ads.models import AdImpression, AdPlacement
from apps.gamification.models import CoinTransaction
from apps.learning import services as learn
from apps.learning.models import DailyActivity

pytestmark = pytest.mark.django_db


@pytest.fixture
def token(api, user, password):
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


@pytest.fixture
def ready_user(user, settings):
    """Tài khoản đã qua giai đoạn ân hạn: đủ tuổi và đủ số bài học."""
    settings.ADS_ENABLED = True
    settings.ADS_SSV_REQUIRED = False
    user.date_joined = djtz.now() - timedelta(days=30)
    user.save(update_fields=["date_joined"])
    DailyActivity.objects.create(user=user, date=date(2020, 1, 1), lessons_completed=20)
    ensure_profile(user)
    return user


@pytest.fixture
def placements(ready_user):
    seed_ads()
    AdPlacement.objects.filter(slot__in=["shop_earn", "out_of_hearts"]).update(
        is_enabled=True, cooldown_seconds=0
    )
    return AdPlacement.objects.in_bulk(field_name="slot")


def _open(api, token, slot="shop_earn", game_code=""):
    return api.post("/ads/impressions", {"slot": slot, "game_code": game_code}, token=token)


def _claim(api, token, impression_id):
    return api.post(f"/ads/impressions/{impression_id}/claim", token=token)


def test_config_lists_placements_with_remaining(api, token, placements, settings):
    settings.ADS_MIN_INTERVAL_SEC = 0
    body = api.get("/ads/config", token=token).json()
    assert body["enabled"] is True
    assert body["global_daily_cap"] == settings.ADS_GLOBAL_DAILY_CAP
    shop_earn = next(p for p in body["placements"] if p["slot"] == "shop_earn")
    assert shop_earn["reward_kind"] == "coins"
    assert shop_earn["remaining_today"] == shop_earn["daily_cap"]
    assert shop_earn["blocked_reason"] is None
    # Vị trí chưa bật vẫn trả về để client biết, nhưng kèm lý do.
    session_end = next(p for p in body["placements"] if p["slot"] == "session_end")
    assert session_end["blocked_reason"] == "slot_disabled"


def test_premium_khong_co_quang_cao(api, token, placements, user):
    profile = ensure_profile(user)
    profile.is_premium = True
    profile.save(update_fields=["is_premium"])
    body = api.get("/ads/config", token=token).json()
    assert body["enabled"] is False
    assert body["blocked_reason"] == "premium"
    assert _open(api, token).status_code == 409


def test_tai_khoan_moi_trong_thoi_gian_an_han(api, token, user, settings):
    settings.ADS_ENABLED = True
    seed_ads()
    AdPlacement.objects.filter(slot="shop_earn").update(is_enabled=True)
    body = api.get("/ads/config", token=token).json()
    assert body["blocked_reason"] == "grace_period"
    assert _open(api, token).json()["error"]["code"] == "grace_period"


def test_ve_va_thuong_xu(api, token, placements, user, settings):
    settings.ADS_MIN_INTERVAL_SEC = 0
    ticket = _open(api, token).json()
    assert ticket["custom_data"] == ticket["impression_id"]
    before = ensure_profile(user).coins

    body = _claim(api, token, ticket["impression_id"]).json()
    assert body["status"] == "rewarded"
    assert body["granted_amount"] == 20
    assert body["coins"] == before + 20
    assert CoinTransaction.objects.filter(user=user, reason="ad_reward", amount=20).exists()

    # Gọi lại không cộng thêm.
    again = _claim(api, token, ticket["impression_id"]).json()
    assert again["coins"] == before + 20


def test_tran_ngay_theo_vi_tri(api, token, placements, settings):
    settings.ADS_MIN_INTERVAL_SEC = 0
    for _ in range(3):
        assert _open(api, token).status_code == 200
    blocked = _open(api, token)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "daily_cap"


def test_khoang_cach_giua_hai_luot(api, token, placements, settings):
    settings.ADS_MIN_INTERVAL_SEC = 300
    assert _open(api, token).status_code == 200
    assert _open(api, token).json()["error"]["code"] == "cooldown"


def test_tran_xu_moi_ngay(api, token, placements, settings, user):
    settings.ADS_MIN_INTERVAL_SEC = 0
    settings.ADS_DAILY_COIN_CAP = 30
    first = _open(api, token).json()
    assert _claim(api, token, first["impression_id"]).json()["granted_amount"] == 20
    second = _open(api, token).json()
    # Chỉ còn 10 xu trong trần ngày → nhận đúng phần còn lại.
    assert _claim(api, token, second["impression_id"]).json()["granted_amount"] == 10
    assert _open(api, token).json()["error"]["code"] == "coin_cap"


def test_thuong_tim_va_tim_day(api, token, placements, user, settings):
    settings.ADS_MIN_INTERVAL_SEC = 0
    profile = ensure_profile(user)
    assert _open(api, token, "out_of_hearts").json()["error"]["code"] == "hearts_full"

    profile.hearts = 1
    profile.hearts_updated_at = djtz.now()
    profile.save(update_fields=["hearts", "hearts_updated_at"])
    ticket = _open(api, token, "out_of_hearts").json()
    body = _claim(api, token, ticket["impression_id"]).json()
    assert body["granted_amount"] == 1
    assert body["hearts"] == 2
    assert body["hearts"] <= learn.HEARTS_MAX


def test_ve_het_han_khong_nhan_duoc_thuong(api, token, placements, settings):
    settings.ADS_MIN_INTERVAL_SEC = 0
    settings.ADS_SSV_REQUIRED = True
    settings.ADS_TICKET_TTL_SEC = 600
    ticket = _open(api, token).json()
    impression = AdImpression.objects.get(id=ticket["impression_id"])
    AdImpression.objects.filter(pk=impression.pk).update(created_at=djtz.now() - timedelta(hours=2))
    assert _claim(api, token, ticket["impression_id"]).json()["status"] == "expired"


def test_callback_ssv_cong_thuong_mot_lan(api, client, token, placements, settings, user):
    settings.ADS_MIN_INTERVAL_SEC = 0
    settings.ADS_SSV_REQUIRED = False
    ticket = _open(api, token).json()
    query = (
        f"ad_network=5450213213286189855&ad_unit=123&custom_data={ticket['impression_id']}"
        f"&reward_amount=20&reward_item=coins&timestamp={int(djtz.now().timestamp() * 1000)}"
        f"&transaction_id=tx-1&user_id={user.id}&signature=abc&key_id=1"
    )
    assert client.get(f"/api/v1/ads/ssv?{query}").status_code == 200
    assert client.get(f"/api/v1/ads/ssv?{query}").status_code == 200
    assert CoinTransaction.objects.filter(user=user, reason="ad_reward").count() == 1
    assert AdImpression.objects.get(id=ticket["impression_id"]).ssv_transaction_id == "tx-1"


def test_ssv_thieu_chu_ky_bi_tu_choi(client, placements):
    assert client.get("/api/v1/ads/ssv?custom_data=x").status_code == 400


def test_nhan_doi_xu_bang_dung_so_xu_van_vua_choi(api, token, placements, user, settings):
    """Thưởng theo ván phải bằng xu vừa nhận, không phải trần của vị trí."""
    settings.ADS_MIN_INTERVAL_SEC = 0
    from apps.gamification.models import Game, GameScore

    AdPlacement.objects.filter(slot="game_win_double").update(is_enabled=True)
    game = Game.objects.create(code="word_rain", title_vi="Mưa từ vựng", description_vi="x")
    GameScore.objects.create(user=user, game=game, level="A1", score=480, coins_earned=6)

    ticket = _open(api, token, "game_win_double", "word_rain").json()
    assert ticket["reward_amount"] == 6

    body = _claim(api, token, ticket["impression_id"]).json()
    assert body["granted_amount"] == 6
    assert CoinTransaction.objects.filter(user=user, reason="ad_reward", amount=6).exists()


def test_nhan_doi_xu_bi_chan_tran_cua_vi_tri(api, token, placements, user, settings):
    settings.ADS_MIN_INTERVAL_SEC = 0
    from apps.gamification.models import Game, GameScore

    AdPlacement.objects.filter(slot="game_win_double").update(is_enabled=True)
    game = Game.objects.create(code="word_rain", title_vi="Mưa từ vựng", description_vi="x")
    GameScore.objects.create(user=user, game=game, level="A1", score=2000, coins_earned=15)

    assert _open(api, token, "game_win_double", "word_rain").json()["reward_amount"] == 15


def test_chua_choi_van_nao_thi_khong_cap_ve_nhan_doi(api, token, placements, settings):
    settings.ADS_MIN_INTERVAL_SEC = 0
    AdPlacement.objects.filter(slot="game_win_double").update(is_enabled=True)

    blocked = _open(api, token, "game_win_double", "word_rain")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "no_reward_context"


def test_mot_van_chi_nhan_doi_duoc_mot_lan(api, token, placements, user, settings):
    """Không cho xem quảng cáo nhiều lần để nhân đôi mãi cùng một ván."""
    settings.ADS_MIN_INTERVAL_SEC = 0
    from apps.gamification.models import Game, GameScore

    AdPlacement.objects.filter(slot="game_win_double").update(is_enabled=True, cooldown_seconds=0)
    game = Game.objects.create(code="word_rain", title_vi="Mưa từ vựng", description_vi="x")
    GameScore.objects.create(user=user, game=game, level="A1", score=480, coins_earned=6)

    first = _open(api, token, "game_win_double", "word_rain").json()
    _claim(api, token, first["impression_id"])

    again = _open(api, token, "game_win_double", "word_rain")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_rewarded"

    # Ván mới thì lại nhân đôi được.
    GameScore.objects.create(user=user, game=game, level="A1", score=800, coins_earned=10)
    assert _open(api, token, "game_win_double", "word_rain").json()["reward_amount"] == 10


def test_nhan_doi_thuong_nhiem_vu_bang_dung_so_xu_vua_nhan(api, token, placements, user, settings):
    """Nhiệm vụ 15 xu thì nhân đôi cho 15, không phải trần 20 của vị trí."""
    settings.ADS_MIN_INTERVAL_SEC = 0
    from apps.accounts.services import ensure_profile
    from apps.gamification import shop

    AdPlacement.objects.filter(slot="challenge_claim_double").update(
        is_enabled=True, cooldown_seconds=0
    )
    profile = ensure_profile(user)
    shop.grant_coins(profile, 15, reason="challenge", ref_type="challenge", ref_id="daily_words")

    ticket = _open(api, token, "challenge_claim_double").json()
    assert ticket["reward_amount"] == 15
    assert _claim(api, token, ticket["impression_id"]).json()["granted_amount"] == 15

    # Cùng một lần nhận thưởng không nhân đôi được hai lần.
    again = _open(api, token, "challenge_claim_double")
    assert again.json()["error"]["code"] == "already_rewarded"


def test_chua_diem_danh_thi_khong_cap_ve_nhan_doi(api, token, placements, settings):
    settings.ADS_MIN_INTERVAL_SEC = 0
    AdPlacement.objects.filter(slot="checkin_double").update(is_enabled=True, cooldown_seconds=0)

    blocked = _open(api, token, "checkin_double")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "no_reward_context"


def test_native_khong_bi_tran_va_cooldown_cua_quang_cao_co_thuong(api, token, placements, settings):
    """Thẻ native không tiêu lượt nào nên không được ăn theo trần/cooldown của rewarded."""
    settings.ADS_MIN_INTERVAL_SEC = 300
    AdPlacement.objects.filter(slot="video_list").update(is_enabled=True)

    # Vừa xem một quảng cáo có thưởng xong: rewarded phải chờ, native thì không.
    ticket = _open(api, token).json()
    _claim(api, token, ticket["impression_id"])

    body = api.get("/ads/config", token=token).json()
    video = next(p for p in body["placements"] if p["slot"] == "video_list")
    shop_earn = next(p for p in body["placements"] if p["slot"] == "shop_earn")
    assert video["blocked_reason"] is None
    assert shop_earn["blocked_reason"] == "cooldown"
