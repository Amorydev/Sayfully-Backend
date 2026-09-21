"""Danh mục vận hành (không phải nội dung học): nhiệm vụ, huy hiệu, vật phẩm cửa hàng, khung avatar,
game, gói Premium/xu, mã quà tặng. Idempotent; chạy sau `reset_content` hoặc trên DB trống.

  python manage.py seed_catalog
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.billing.models import GiftCode, Product
from apps.gamification.avatar_frames import seed_avatar_frames
from apps.gamification.models import Badge, Challenge, Game, ShopItem


def seed_catalog() -> None:
    # Game hoá
    for code, scope, metric, title, target, rx, rc in [
        ("daily_xp", "daily", "xp", "Kiếm 100 XP hôm nay", 100, 0, 20),
        ("daily_words", "daily", "words", "Ôn 20 từ vựng", 20, 0, 15),
        ("daily_speak", "daily", "speaking", "Phát âm chuẩn 15 câu", 15, 0, 25),
        ("daily_ai_talk", "daily", "ai_turns", "Nói 5 câu với Long", 5, 0, 20),
        ("weekly_lessons", "weekly", "lessons", "Học 10 bài trong tuần", 10, 100, 50),
    ]:
        Challenge.objects.update_or_create(
            code=code,
            defaults={
                "scope": scope,
                "metric": metric,
                "title_vi": title,
                "description_vi": title,
                "target": target,
                "reward_xp": rx,
                "reward_coins": rc,
            },
        )
    for code, title, metric, value in [
        ("streak7", "Chuỗi 7 ngày", "streak", 7),
        ("streak30", "Chuỗi 30 ngày", "streak", 30),
        ("level5", "Đạt cấp 5", "level", 5),
    ]:
        Badge.objects.update_or_create(
            code=code,
            defaults={
                "title_vi": title,
                "description_vi": title,
                "condition": {"metric": metric, "value": value},
            },
        )
    # (code, title, desc, cost, effect, category, order, discount_pct, meta)
    for code, title, desc, cost, effect, cat, order, pct, meta in [
        (
            "refill_hearts",
            "Bơm đầy tim",
            "Hồi phục 5/5 tim",
            150,
            {"hearts": 5},
            "booster",
            1,
            0,
            {},
        ),
        (
            "streak_freeze",
            "Băng bảo vệ streak",
            "Đóng băng chuỗi 24h",
            200,
            {"streak_freeze": 1},
            "booster",
            2,
            0,
            {},
        ),
        (
            "xp_boost",
            "Gấp đôi XP",
            "x2 XP trong 15 phút",
            120,
            {"xp_boost": 15},
            "booster",
            3,
            0,
            {},
        ),
        (
            "xp_boost_60",
            "Gấp đôi XP · 1 giờ",
            "x2 XP trong 60 phút",
            350,
            {"xp_boost": 60},
            "booster",
            4,
            20,
            {},
        ),
        (
            "bundle_week",
            "Gói bảo vệ tuần",
            "2 băng streak + bơm đầy tim",
            500,
            {"streak_freeze": 2, "hearts": 5},
            "bundle",
            10,
            20,
            {},
        ),
        (
            "bundle_grind",
            "Gói cày XP",
            "x2 XP 30 phút + bơm đầy tim",
            400,
            {"xp_boost": 30, "hearts": 5},
            "bundle",
            11,
            15,
            {},
        ),
        (
            "mystery_box",
            "Rương may mắn",
            "Ngẫu nhiên: xu, tim, băng hoặc boost XP",
            120,
            {"mystery_box": 1},
            "special",
            20,
            0,
            {},
        ),
        (
            "streak_repair",
            "Hồi sinh streak",
            "Khôi phục chuỗi vừa mất trong 48h",
            350,
            {"streak_repair": 1},
            "special",
            21,
            0,
            {},
        ),
    ]:
        ShopItem.objects.update_or_create(
            code=code,
            defaults={
                "title_vi": title,
                "description_vi": desc,
                "cost_coins": cost,
                "effect": effect,
                "category": cat,
                "order": order,
                "discount_pct": pct,
                "meta": meta,
            },
        )
    seed_avatar_frames()
    for code, title, desc, kind, featured, order in [
        ("word_rain", "Mưa từ vựng", "Hứng bóng chữ rơi đúng nghĩa", "reflex", True, 1),
        ("match_pairs", "Ghép cặp", "Nối từ tiếng Anh và nghĩa Việt", "memory", False, 2),
        (
            "stress_master",
            "Bậc thầy trọng âm",
            "Bắt đúng âm tiết được nhấn",
            "reflex",
            False,
            3,
        ),
        ("speed_type", "Gõ nhanh 60s", "Thử thách tốc độ gõ phím", "reflex", False, 4),
        (
            "speed_say",
            "Nói nhanh",
            "Đọc to từ trước khi hết giờ",
            "speaking",
            False,
            5,
        ),
    ]:
        Game.objects.update_or_create(
            code=code,
            defaults={
                "title_vi": title,
                "description_vi": desc,
                "kind": kind,
                "is_featured": featured,
                "order": order,
            },
        )

    # Thanh toán
    for code, name, period, price, orig, trial, badge, order in [
        ("premium_month", "Gói Tháng", "month", 79000, None, 0, "", 1),
        ("premium_year", "Gói Năm", "year", 499000, 948000, 0, "TIẾT KIỆM 47%", 2),
        ("premium_lifetime", "Trọn đời", "lifetime", 999000, None, 0, "MUA 1 LẦN", 3),
    ]:
        Product.objects.update_or_create(
            code=code,
            defaults={
                "name_vi": name,
                "kind": "premium",
                "tier": "premium",
                "period": period,
                "price": price,
                "original_price": orig,
                "trial_days": trial,
                "badge_vi": badge,
                "features": [
                    {
                        "title": "Mở toàn bộ bài PRO lộ trình A1–C2",
                        "description": "Lộ trình bài bản từ sơ cấp đến thành thạo phản xạ",
                        "icon_url": "billing/features/pro.png",
                    },
                    {
                        "title": "Tim không giới hạn",
                        "description": "Sai không mất tim, học liền mạch không gián đoạn",
                        "icon_url": "billing/features/hearts.png",
                    },
                    {
                        "title": "Gia sư AI 30 lượt/ngày",
                        "description": "Sửa phát âm và hội thoại 1–1 theo chuẩn bản ngữ",
                        "icon_url": "billing/features/ai.png",
                    },
                    {
                        "title": "Sổ tay 4.000 từ",
                        "description": "Lưu, ôn và tra từ mọi lúc ngay cả khi không mạng",
                        "icon_url": "billing/features/notebook.png",
                    },
                    {
                        "title": "Thêm 3 video YouTube mỗi ngày",
                        "description": "Luyện nghe với phụ đề song ngữ và IPA",
                        "icon_url": "billing/features/video.png",
                    },
                    {
                        "title": "+50% xu · Không quảng cáo",
                        "description": "Tối đa sự tập trung trong từng phút học cùng Long",
                        "icon_url": "billing/features/coins.png",
                    },
                ],
                "store_ids": {"revenuecat": f"sayfully_{code}", "payos": code},
                "order": order,
            },
        )
    for code, name, coins, price, badge, order in [
        ("coins_500", "500 xu", 500, 19000, "", 10),
        ("coins_1200", "1.200 xu", 1200, 39000, "PHỔ BIẾN", 11),
        ("coins_3000", "3.000 xu", 3000, 79000, "LỢI NHẤT", 12),
    ]:
        Product.objects.update_or_create(
            code=code,
            defaults={
                "name_vi": name,
                "kind": "coins",
                "coins": coins,
                "period": "one_time",
                "price": price,
                "badge_vi": badge,
                "features": [],
                "store_ids": {"revenuecat": f"sayfully_{code}", "payos": code},
                "order": order,
            },
        )
    GiftCode.objects.update_or_create(code="SAYFULLY30", defaults={"days": 30, "max_uses": 100})


class Command(BaseCommand):
    help = "Nạp danh mục vận hành: nhiệm vụ, huy hiệu, cửa hàng, khung avatar, game, gói Premium/xu, mã quà."

    def handle(self, *args, **opts):
        with transaction.atomic():
            seed_catalog()
        self.stdout.write(
            self.style.SUCCESS(
                f"Catalog: {Challenge.objects.count()} nhiệm vụ · {Badge.objects.count()} huy hiệu · "
                f"{ShopItem.objects.count()} vật phẩm · {Game.objects.count()} game · "
                f"{Product.objects.count()} gói · {GiftCode.objects.count()} mã quà"
            )
        )
