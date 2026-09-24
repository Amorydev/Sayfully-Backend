"""Bổ sung 10 tài khoản học viên ban đầu chân thực và đẹp mắt cho Sayfully khi launch.

Bao gồm:
- Họ tên tiếng Việt, ảnh đại diện chân dung chất lượng cao.
- Cấp độ CEFR đa dạng (A1 -> B2), mục tiêu học tập (Daily, Work, Study, Travel, Exam).
- Chuỗi streak hoạt động liên tục (3 -> 42 ngày).
- Khung avatar trang trí cao cấp (Hoàng Gia, Rồng Lửa, Cực Quang, Ngân Hà, v.v.).
- Thành tích liên đoàn tuần hiện tại (Tier BRONZE) tạo bục vinh danh Top 1-3 và bậc thang cạnh tranh.
- Thống kê tuần (WeeklyStat) và lịch sử hoạt động hằng ngày (DailyActivity).
- Huy hiệu phù hợp (chuỗi 7 ngày, 30 ngày, cấp 5).
- Mật khẩu mặc định: Sayfully@123 (có thể tuỳ chỉnh qua --password).

Cách chạy:
  python manage.py seed_initial_accounts
  python manage.py seed_initial_accounts --password MyPassword123
"""

from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone as djtz

from apps.accounts.models import User, UserProfile
from apps.accounts.services import ensure_profile
from apps.common.models import CEFR, Accent, LearningGoal
from apps.common.management.commands.seed_catalog import seed_catalog
from apps.gamification.avatar_frames import seed_avatar_frames
from apps.gamification.models import Badge, LeagueGroup, LeagueMembership, ShopItem, UserBadge, UserCosmetic
from apps.gamification.services import current_week
from apps.learning.models import DailyActivity, WeeklyStat

DEFAULT_PASSWORD = "Sayfully@123"

# Danh sách 10 tài khoản mẫu phong phú, chân thực
INITIAL_ACCOUNTS = [
    {
        "email": "hoang.minh@sayfully.app",
        "full_name": "Hoàng Minh",
        "avatar_url": "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?auto=format&fit=crop&w=300&q=80",
        "cefr_level": CEFR.B2,
        "goal_level": CEFR.C1,
        "learning_goal": LearningGoal.TOEIC,
        "level": 9,
        "xp_total": 7850,
        "xp_week": 2680,
        "coins": 1850,
        "streak": 42,
        "accent": Accent.US,
        "is_premium": True,
        "avatar_frame": "frame_imperial",
    },
    {
        "email": "bao.tran@sayfully.app",
        "full_name": "Bảo Trân",
        "avatar_url": "https://images.unsplash.com/photo-1517841905240-472988babdf9?auto=format&fit=crop&w=300&q=80",
        "cefr_level": CEFR.B1,
        "goal_level": CEFR.B2,
        "learning_goal": LearningGoal.IELTS,
        "level": 8,
        "xp_total": 6420,
        "xp_week": 2240,
        "coins": 1420,
        "streak": 28,
        "accent": Accent.UK,
        "is_premium": True,
        "avatar_frame": "frame_dragon",
    },
    {
        "email": "khanh.linh@sayfully.app",
        "full_name": "Khánh Linh",
        "avatar_url": "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?auto=format&fit=crop&w=300&q=80",
        "cefr_level": CEFR.B1,
        "goal_level": CEFR.B2,
        "learning_goal": LearningGoal.DAILY,
        "level": 7,
        "xp_total": 5180,
        "xp_week": 1890,
        "coins": 980,
        "streak": 19,
        "accent": Accent.US,
        "is_premium": True,
        "avatar_frame": "frame_aurora",
    },
    {
        "email": "duc.huy@sayfully.app",
        "full_name": "Đức Huy",
        "avatar_url": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=300&q=80",
        "cefr_level": CEFR.A2,
        "goal_level": CEFR.B1,
        "learning_goal": LearningGoal.TRAVEL,
        "level": 6,
        "xp_total": 4120,
        "xp_week": 1520,
        "coins": 850,
        "streak": 15,
        "accent": Accent.US,
        "is_premium": False,
        "avatar_frame": "frame_galaxy",
    },
    {
        "email": "mai.anh@sayfully.app",
        "full_name": "Mai Anh",
        "avatar_url": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=300&q=80",
        "cefr_level": CEFR.A2,
        "goal_level": CEFR.B2,
        "learning_goal": LearningGoal.DAILY,
        "level": 5,
        "xp_total": 3450,
        "xp_week": 1280,
        "coins": 650,
        "streak": 11,
        "accent": Accent.US,
        "is_premium": True,
        "avatar_frame": "frame_blossom",
    },
    {
        "email": "quoc.trung@sayfully.app",
        "full_name": "Quốc Trung",
        "avatar_url": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=300&q=80",
        "cefr_level": CEFR.A2,
        "goal_level": CEFR.B1,
        "learning_goal": LearningGoal.TOEIC,
        "level": 5,
        "xp_total": 2890,
        "xp_week": 1050,
        "coins": 520,
        "streak": 8,
        "accent": Accent.US,
        "is_premium": False,
        "avatar_frame": "frame_thunder",
    },
    {
        "email": "thu.trang@sayfully.app",
        "full_name": "Thu Trang",
        "avatar_url": "https://images.unsplash.com/photo-1438761681033-6461ffad8d80?auto=format&fit=crop&w=300&q=80",
        "cefr_level": CEFR.A1,
        "goal_level": CEFR.B1,
        "learning_goal": LearningGoal.DAILY,
        "level": 4,
        "xp_total": 2150,
        "xp_week": 870,
        "coins": 410,
        "streak": 7,
        "accent": Accent.UK,
        "is_premium": False,
        "avatar_frame": "frame_sakura",
    },
    {
        "email": "hai.dang@sayfully.app",
        "full_name": "Hải Đăng",
        "avatar_url": "https://images.unsplash.com/photo-1492562080023-ab3db95bfbce?auto=format&fit=crop&w=300&q=80",
        "cefr_level": CEFR.A1,
        "goal_level": CEFR.A2,
        "learning_goal": LearningGoal.TRAVEL,
        "level": 3,
        "xp_total": 1620,
        "xp_week": 690,
        "coins": 320,
        "streak": 5,
        "accent": Accent.US,
        "is_premium": False,
        "avatar_frame": "frame_frost",
    },
    {
        "email": "lan.phuong@sayfully.app",
        "full_name": "Lan Phương",
        "avatar_url": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=300&q=80",
        "cefr_level": CEFR.A1,
        "goal_level": CEFR.B1,
        "learning_goal": LearningGoal.IELTS,
        "level": 3,
        "xp_total": 1240,
        "xp_week": 530,
        "coins": 240,
        "streak": 4,
        "accent": Accent.US,
        "is_premium": True,
        "avatar_frame": "frame_angel",
    },
    {
        "email": "tuan.kiet@sayfully.app",
        "full_name": "Tuấn Kiệt",
        "avatar_url": "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?auto=format&fit=crop&w=300&q=80",
        "cefr_level": CEFR.A1,
        "goal_level": CEFR.A2,
        "learning_goal": LearningGoal.DAILY,
        "level": 2,
        "xp_total": 850,
        "xp_week": 380,
        "coins": 180,
        "streak": 3,
        "accent": Accent.US,
        "is_premium": False,
        "avatar_frame": "frame_neon",
    },
]


class Command(BaseCommand):
    help = "Khởi tạo 10 tài khoản học viên ban đầu với dữ liệu đẹp và đầy đủ khi launch Sayfully"

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            type=str,
            default=DEFAULT_PASSWORD,
            help=f"Mật khẩu đăng nhập cho cả 10 tài khoản (mặc định: {DEFAULT_PASSWORD})",
        )

    def handle(self, *args, **options):
        password = options["password"]
        created_count, updated_count = seed_initial_accounts(password=password)
        self.stdout.write(
            self.style.SUCCESS(
                f"Đã hoàn thành khởi tạo: {created_count} tạo mới, {updated_count} cập nhật. "
                f"Tổng cộng: {len(INITIAL_ACCOUNTS)} tài khoản (mật khẩu: {password})."
            )
        )


@transaction.atomic
def seed_initial_accounts(password: str = DEFAULT_PASSWORD) -> tuple[int, int]:
    # Đồng bộ catalog (huy hiệu, thử thách, vật phẩm, khung avatar) trước nếu chưa có
    seed_catalog()
    seed_avatar_frames()

    now = djtz.now()
    today = now.date()
    iso_year, iso_week = current_week()

    # Nhóm Liên đoàn Đồng (Tier.BRONZE) tuần hiện tại cho người mới
    league_group, _ = LeagueGroup.objects.get_or_create(
        tier=LeagueGroup.Tier.BRONZE,
        iso_year=iso_year,
        iso_week=iso_week,
    )

    created_count = 0
    updated_count = 0

    for acc in INITIAL_ACCOUNTS:
        email = acc["email"]
        full_name = acc["full_name"]
        avatar_url = acc["avatar_url"]

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "full_name": full_name,
                "avatar_path": avatar_url,
                "is_active": True,
            },
        )
        if created:
            user.set_password(password)
            user.save()
            created_count += 1
        else:
            user.full_name = full_name
            user.avatar_path = avatar_url
            user.set_password(password)
            user.save(update_fields=["full_name", "avatar_path", "password"])
            updated_count += 1

        profile = ensure_profile(user)
        profile.cefr_level = acc["cefr_level"]
        profile.goal_level = acc["goal_level"]
        profile.learning_goal = acc["learning_goal"]
        profile.level = acc["level"]
        profile.xp_total = acc["xp_total"]
        profile.coins = acc["coins"]
        profile.hearts = 5
        profile.streak_current = acc["streak"]
        profile.streak_best = acc["streak"] + 3
        profile.accent = acc["accent"]
        profile.is_premium = acc["is_premium"]
        profile.avatar_frame = acc["avatar_frame"]
        profile.onboarding_completed = True
        profile.onboarding_completed_at = now
        profile.last_active_date = today
        profile.save()

        # Mở quyền sở hữu khung avatar trong Shop nếu có
        frame_code = acc["avatar_frame"]
        if frame_code:
            item = ShopItem.objects.filter(code=frame_code).first()
            if item:
                UserCosmetic.objects.get_or_create(user=user, item=item)

        # Gán huy hiệu tương ứng
        if acc["streak"] >= 7:
            b = Badge.objects.filter(code="streak7").first()
            if b:
                UserBadge.objects.get_or_create(user=user, badge=b)
        if acc["streak"] >= 30:
            b = Badge.objects.filter(code="streak30").first()
            if b:
                UserBadge.objects.get_or_create(user=user, badge=b)
        if acc["level"] >= 5:
            b = Badge.objects.filter(code="level5").first()
            if b:
                UserBadge.objects.get_or_create(user=user, badge=b)

        # Xếp hạng liên đoàn tuần và WeeklyStat
        xp_week = acc["xp_week"]
        LeagueMembership.objects.update_or_create(
            group=league_group,
            user=user,
            defaults={"xp_week": xp_week},
        )
        WeeklyStat.objects.update_or_create(
            user=user,
            iso_year=iso_year,
            iso_week=iso_week,
            defaults={"xp": xp_week, "days_active": min(acc["streak"], 7)},
        )

        # Lịch sử hoạt động hằng ngày (3 - 7 ngày gần nhất)
        days_to_seed = min(acc["streak"], 7)
        daily_base_xp = xp_week // days_to_seed
        for day_offset in range(days_to_seed):
            act_date = today - timedelta(days=day_offset)
            # Biến thiên nhẹ giữa các ngày để tự nhiên
            day_xp = daily_base_xp + ((day_offset * 17) % 30) - 15
            DailyActivity.objects.update_or_create(
                user=user,
                date=act_date,
                defaults={
                    "xp": max(30, day_xp),
                    "lessons_completed": 2 if day_offset % 2 == 0 else 1,
                    "words_reviewed": 12 + (day_offset * 3),
                    "speaking_count": 5 + day_offset,
                    "listening_count": 4 + (day_offset % 3),
                    "ai_turns": 3 if acc["is_premium"] else 0,
                    "minutes": 15 + day_offset * 2,
                },
            )

    return created_count, updated_count
