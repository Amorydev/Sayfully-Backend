"""Nạp cấu hình vị trí quảng cáo theo spec `2026-09-23-ads-placement-design.md`.

  python manage.py seed_ads

Idempotent, và **không** đụng tới `is_enabled` của vị trí đã có — chạy lại không bật nhầm gì.

Vị trí mới nạp ở trạng thái tắt — bật từng cái trong admin theo lộ trình
(§9 của spec: rewarded trước, native sau, interstitial cuối cùng và chỉ khi A/B cho phép).
Ad unit mặc định là bộ ID *thử nghiệm* chính thức của Google. Khai `ADS_REWARDED_AD_UNIT_ANDROID`
/ `ADS_REWARDED_AD_UNIT_IOS` trong `.env` (chỉ ở môi trường thật) để các vị trí có thưởng dùng ID thật —
máy dev không khai thì vẫn chạy quảng cáo test, không có rủi ro bấm nhầm quảng cáo thật.
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.ads.models import AdPlacement

REWARDED_TEST = ("ca-app-pub-3940256099942544/5224354917", "ca-app-pub-3940256099942544/1712485313")
INTERSTITIAL_TEST = (
    "ca-app-pub-3940256099942544/1033173712",
    "ca-app-pub-3940256099942544/4411468910",
)
NATIVE_TEST = ("ca-app-pub-3940256099942544/2247696110", "ca-app-pub-3940256099942544/3986624511")

F = AdPlacement.Format
R = AdPlacement.Reward

# (slot, tiêu đề, mô tả, format, loại thưởng, mức thưởng, trần ngày, cooldown giây, ad unit, thứ tự)
PLACEMENTS = [
    (
        "out_of_hearts",
        "Hết tim",
        "Sheet hết tim: xem quảng cáo nhận 1 tim thay vì chờ 30 phút",
        F.REWARDED,
        R.HEARTS,
        1,
        2,
        60,
        REWARDED_TEST,
        1,
    ),
    (
        "game_over",
        "Thua ván game",
        "Kết quả thua Word Rain / Stress Master: nhận 1 tim để chơi tiếp",
        F.REWARDED,
        R.HEARTS,
        1,
        3,
        60,
        REWARDED_TEST,
        2,
    ),
    (
        "game_win_double",
        "Nhân đôi xu ván thắng",
        "Kết quả mini-game: nhân đôi đúng số xu vừa nhận, trần 15 xu",
        F.REWARDED,
        R.COINS,
        15,
        3,
        60,
        REWARDED_TEST,
        3,
    ),
    (
        "shop_earn",
        "Kiếm xu ở Cửa hàng",
        "Dòng cố định trong sheet Kiếm xu hôm nay",
        F.REWARDED,
        R.COINS,
        20,
        3,
        60,
        REWARDED_TEST,
        4,
    ),
    (
        "checkin_double",
        "Nhân đôi thưởng điểm danh",
        "Chỉ ở trạng thái đã điểm danh xong, không hiện khi chuỗi đang nguy hiểm",
        F.REWARDED,
        R.COINS,
        10,
        1,
        60,
        REWARDED_TEST,
        5,
    ),
    (
        "challenge_claim_double",
        "Nhân đôi thưởng nhiệm vụ",
        "Khi nhận thưởng nhiệm vụ ở tab Thử thách",
        F.REWARDED,
        R.COINS,
        20,
        2,
        60,
        REWARDED_TEST,
        6,
    ),
    (
        "session_end",
        "Kết thúc phiên",
        "Rời VideoWatch hoặc rời mini-game từ ván thứ hai — không bao giờ sau bài học",
        F.INTERSTITIAL,
        R.NONE,
        0,
        2,
        180,
        INTERSTITIAL_TEST,
        10,
    ),
    (
        "video_list",
        "Danh sách Video",
        "Một thẻ native chèn giữa hai block thể loại",
        F.NATIVE,
        R.NONE,
        0,
        20,
        0,
        NATIVE_TEST,
        20,
    ),
    (
        "shop_footer",
        "Cuối tab Cửa hàng",
        "Thẻ native dưới các section",
        F.NATIVE,
        R.NONE,
        0,
        20,
        0,
        NATIVE_TEST,
        21,
    ),
]


def _units(fmt: str, default: tuple[str, str]) -> tuple[str, str]:
    if fmt not in (F.REWARDED, F.REWARDED_INTERSTITIAL):
        return default
    return (
        settings.ADS_REWARDED_AD_UNIT_ANDROID or default[0],
        settings.ADS_REWARDED_AD_UNIT_IOS or default[1],
    )


def seed_ads() -> None:
    for slot, title, desc, fmt, reward, amount, cap, cooldown, defaults, order in PLACEMENTS:
        units = _units(fmt, defaults)
        # Vị trí "nhân đôi" phải cộng đúng bằng thứ người dùng vừa nhận, không phải mức cố định.
        source, reason = {
            "game_win_double": (AdPlacement.RewardSource.LAST_GAME_COINS, ""),
            "checkin_double": (AdPlacement.RewardSource.LAST_COIN_REWARD, "checkin"),
            "challenge_claim_double": (AdPlacement.RewardSource.LAST_COIN_REWARD, "challenge"),
        }.get(slot, (AdPlacement.RewardSource.FIXED, ""))
        AdPlacement.objects.update_or_create(
            slot=slot,
            defaults={
                "title_vi": title,
                "description_vi": desc,
                "format": fmt,
                "reward_kind": reward,
                "reward_source": source,
                "reward_reason": reason,
                "reward_amount": amount,
                "daily_cap": cap,
                "cooldown_seconds": cooldown,
                "ad_unit_android": units[0],
                "ad_unit_ios": units[1],
                "order": order,
            },
        )


class Command(BaseCommand):
    help = "Nạp vị trí quảng cáo (tắt sẵn); bật từng vị trí trong admin theo lộ trình."

    def handle(self, *args, **opts):
        with transaction.atomic():
            seed_ads()
        enabled = AdPlacement.objects.filter(is_enabled=True).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Quảng cáo: {AdPlacement.objects.count()} vị trí · {enabled} đang bật"
            )
        )
