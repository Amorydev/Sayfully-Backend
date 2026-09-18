"""Client-rendered avatar frames; codes are shared with Android AvatarFrameStyle."""

from django.db import transaction

from apps.gamification.models import ShopItem

# code, title, description, initial price, palette, animated
AVATAR_FRAMES = (
    ("frame_gold", "Hoàng Kim", "Vương miện và viền vàng óng", 500, ["#FFE6A3", "#C78A29", "#FFD66E"], False),
    ("frame_aurora", "Cực Quang", "Dải cực quang xanh tím chuyển sắc", 800, ["#52E5CC", "#7F7BFA", "#F2A6E4"], False),
    ("frame_galaxy", "Ngân Hà", "Quỹ đạo và ngôi sao giữa ngân hà", 900, ["#A993FF", "#5144AE", "#72CFFF"], False),
    ("frame_sakura", "Anh Đào", "Cụm hoa anh đào hồng dịu", 700, ["#FFC6DB", "#DF7AA7", "#FFE1ED"], False),
    ("frame_dragon", "Rồng Lửa", "Khung động · rồng và ngọn lửa chuyển động", 1400, ["#FFD779", "#E45135", "#FF9248"], True),
    ("frame_frost", "Băng Pha Lê", "Khung động · tinh thể lấp lánh, tuyết rơi", 1100, ["#D5F9FF", "#65A9EA", "#AAE9FF"], True),
    ("frame_orbit", "Thiên Hà", "Khung động · hành tinh quay quanh avatar", 1300, ["#C2AEFF", "#6555CA", "#73DDF3"], True),
    ("frame_thunder", "Sấm Sét", "Khung động · tia điện chạy dọc viền", 1200, ["#E7D4FF", "#8055E8", "#FFD76E"], True),
    ("frame_blossom", "Hoa Anh Đào", "Khung động · cánh hoa nhẹ nhàng bay", 1000, ["#FFD5E6", "#E77EAD", "#A8DDC0"], True),
    ("frame_angel", "Thiên Thần", "Khung động · đôi cánh và hào quang", 1500, ["#FFF0CA", "#91B9DF", "#F3F8FF"], True),
    ("frame_neon", "Neon RGB", "Khung động · ánh neon đổi màu liên tục", 650, ["#FA73DE", "#7775FA", "#62EFCE"], True),
    ("frame_imperial", "Hoàng Gia", "Khung động · vương miện và ánh vàng lấp lánh", 1800, ["#FFE7A0", "#C98B36", "#9464BC"], True),
)


@transaction.atomic
def seed_avatar_frames():
    """Idempotent catalog sync. Never reset pricing, availability, IDs or ownership."""
    created_count = 0
    for index, (code, title, description, price, colors, animated) in enumerate(AVATAR_FRAMES):
        item, created = ShopItem.objects.get_or_create(
            code=code,
            defaults={
                "title_vi": f"Khung {title}",
                "description_vi": description,
                "cost_coins": price,
                "effect": {"cosmetic": 1},
                "category": ShopItem.Category.COSMETIC,
                "order": 30 + index,
            },
        )
        if item.category != ShopItem.Category.COSMETIC:
            raise ValueError(f"Catalog code {code} is already used by a non-cosmetic item")
        item.title_vi = f"Khung {title}"
        item.description_vi = description
        item.meta = {**item.meta, "slot": "avatar_frame", "colors": colors, "animated": animated}
        item.save(update_fields=["title_vi", "description_vi", "meta"])
        created_count += int(created)
    return created_count
