"""Nạp DATA MẪU cho màn Thử thách (C6) — GET /api/v1/challenges/overview.

Phủ đủ mọi nhánh UI của màn: liên đoàn tuần (bậc/hạng/top %/còn bao nhiêu XP để lên hạng),
3 vòng "Mục tiêu hôm nay", 7 ô chuỗi ngày của tuần, thẻ điểm danh và nhiệm vụ hằng ngày ở
cả 4 trạng thái (đã nhận · chờ nhận · đang làm · chưa làm).

Mọi số liệu suy ra từ DailyActivity nên WeeklyStat / UserProfile / liên đoàn luôn khớp nhau
đúng như `learning.services.record` ghi khi chạy thật. Idempotent — chạy lại không nhân đôi.

`seed_demo` cũng gieo 4 mã thử thách, hoạt động ngày và liên đoàn của user demo với số nhỏ hơn,
nên phải chạy lệnh này SAU `seed_demo` (chạy ngược lại sẽ bị ghi đè).

    uv run python manage.py seed_challenges
    uv run python manage.py seed_challenges --checked-in   # thẻ điểm danh -> "Đã điểm danh"
    uv run python manage.py seed_challenges --email me@sayfully.app
"""

from datetime import datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone as djtz

from apps.accounts.models import User
from apps.accounts.services import ensure_profile
from apps.gamification.models import (
    Challenge,
    CoinTransaction,
    LeagueGroup,
    LeagueMembership,
    UserChallenge,
)
from apps.gamification.services import period_key
from apps.learning.models import DailyActivity, WeeklyStat
from apps.learning.services import local_today

DEMO_EMAIL = "demo@sayfully.app"
DEMO_PASSWORD = "demo1234"
DEMO_NAME = "Quyền Ngọc"

DAILY_GOAL_XP = 150
DAILY_GOAL_WORDS = 20
COINS = 850
HEARTS = 5
MIN_STREAK = 4  # tối thiểu 4 ngày; luôn nới ra đủ từ thứ Hai để tuần này kín ô

# Hôm nay = ngày đang học dở -> khớp thiết kế: XP 120/150, ôn 18/20, nói 12/15 (~83%).
TODAY_ACTIVITY = {
    "xp": 120,
    "words_reviewed": 18,
    "speaking_count": 12,
    "listening_count": 8,
    "lessons_completed": 1,
    "minutes": 15,
}
# Các ngày trước (gần -> xa), lặp lại nếu chuỗi dài hơn danh sách.
PAST_ACTIVITY = [
    {
        "xp": 420,
        "words_reviewed": 46,
        "speaking_count": 22,
        "listening_count": 15,
        "lessons_completed": 6,
        "minutes": 52,
    },
    {
        "xp": 450,
        "words_reviewed": 52,
        "speaking_count": 26,
        "listening_count": 17,
        "lessons_completed": 7,
        "minutes": 58,
    },
    {
        "xp": 430,
        "words_reviewed": 48,
        "speaking_count": 24,
        "listening_count": 16,
        "lessons_completed": 6,
        "minutes": 55,
    },
    {
        "xp": 385,
        "words_reviewed": 40,
        "speaking_count": 19,
        "listening_count": 13,
        "lessons_completed": 5,
        "minutes": 47,
    },
    {
        "xp": 465,
        "words_reviewed": 55,
        "speaking_count": 27,
        "listening_count": 18,
        "lessons_completed": 7,
        "minutes": 60,
    },
    {
        "xp": 405,
        "words_reviewed": 43,
        "speaking_count": 21,
        "listening_count": 14,
        "lessons_completed": 6,
        "minutes": 50,
    },
    {
        "xp": 395,
        "words_reviewed": 41,
        "speaking_count": 20,
        "listening_count": 14,
        "lessons_completed": 5,
        "minutes": 49,
    },
]
# Chuỗi cũ (trước một khoảng nghỉ) để streak_best và xp_total có gốc thật.
GAP_DAYS = 2
OLD_STREAK = [165, 190, 145, 210, 175, 130, 155]

# Nhiệm vụ hằng ngày — thứ tự hiển thị theo (tier, code).
# metric quyết định icon/màu trên màn: xp · words · speaking · lessons · còn lại = gamepad.
DAILY_CHALLENGES = [
    (
        "daily_xp",
        "xp",
        1,
        "Kiếm 100 XP hôm nay",
        "Học bài, ôn từ hay chơi mini-game đều được tính XP.",
        100,
        0,
        20,
    ),
    (
        "daily_words",
        "words",
        2,
        "Ôn 20 từ vựng",
        "Mở hộp ôn tập và trả lời hết số thẻ đến hạn hôm nay.",
        20,
        0,
        15,
    ),
    (
        "daily_speak",
        "speaking",
        3,
        "Phát âm chuẩn 15 câu",
        "Vào Luyện nói, đọc theo và đạt điểm phát âm từ 80% trở lên.",
        15,
        0,
        25,
    ),
    (
        "daily_lesson",
        "lessons",
        4,
        "Hoàn thành 1 bài học",
        "Học xong một bài trong lộ trình, đủ 9 màn từ từ vựng đến quiz.",
        1,
        10,
        15,
    ),
    (
        "daily_active",
        "days",
        5,
        "Mở app và học hôm nay",
        "Chỉ cần có hoạt động ghi nhận trong ngày là đạt.",
        1,
        5,
        5,
    ),
    (
        "daily_exam",
        "exams",
        6,
        "Làm 1 đề luyện thi",
        "Chọn một đề trong Luyện thi và làm hết phần đầu tiên.",
        1,
        20,
        30,
    ),
]

# Nhiệm vụ tuần — cùng catalog, cho /challenges/weekly không rỗng.
WEEKLY_CHALLENGES = [
    (
        "weekly_lessons",
        "lessons",
        1,
        "Học 10 bài trong tuần",
        "Mỗi bài trong lộ trình được tính một lần.",
        10,
        100,
        50,
    ),
    (
        "weekly_xp",
        "xp",
        2,
        "Tích luỹ 1.500 XP tuần này",
        "XP tuần cũng là điểm xếp hạng liên đoàn.",
        1500,
        120,
        60,
    ),
    (
        "weekly_days",
        "days",
        3,
        "Học đủ 5 ngày trong tuần",
        "Giữ chuỗi để không mất bậc liên đoàn.",
        5,
        80,
        40,
    ),
    (
        "weekly_words",
        "words",
        4,
        "Ôn 150 từ vựng trong tuần",
        "Cộng dồn toàn bộ số thẻ đã ôn từ thứ Hai.",
        150,
        90,
        45,
    ),
]

# Trạng thái nhận thưởng gieo sẵn (code -> đã nhận chưa).
# daily_xp: "Đã nhận" · daily_lesson + daily_active: "Nhận" · còn lại: chưa đủ điều kiện.
CLAIMED_DAILY = {"daily_xp"}
CLAIMED_WEEKLY = {"weekly_lessons"}

# Liên đoàn Kim cương, demo đứng hạng 4 trong nhóm 82 người -> Top 5%.
RIVALS = [
    ("linh.tran@demo.sayfully", "Linh Trần", 1.72),
    ("minh.pham@demo.sayfully", "Minh Phạm", 1.39),
    ("an.nguyen@demo.sayfully", "An Nguyễn", 1.13),
    ("hoa.le@demo.sayfully", "Hoa Lê", 0.63),
    ("nam.vo@demo.sayfully", "Nam Võ", 0.49),
]
FILLER_MEMBERS = 76
CHECKIN_COINS = 10  # khớp _CHECKIN_COINS trong learning/api.py


class Command(BaseCommand):
    help = "Nạp data mẫu đầy đủ cho màn Thử thách (C6) — idempotent."

    def add_arguments(self, parser):
        parser.add_argument("--email", default=DEMO_EMAIL, help="Tài khoản nhận data mẫu.")
        parser.add_argument(
            "--checked-in",
            action="store_true",
            help='Gieo sẵn giao dịch điểm danh hôm nay -> thẻ hiện "Đã điểm danh".',
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        user = self._user(opts["email"])
        profile = ensure_profile(user)
        profile.timezone = profile.timezone or "Asia/Ho_Chi_Minh"
        profile.daily_goal_xp = DAILY_GOAL_XP
        profile.daily_goal_words = DAILY_GOAL_WORDS
        profile.save(update_fields=["timezone", "daily_goal_xp", "daily_goal_words"])

        today = local_today(profile)
        streak = max(MIN_STREAK, today.weekday() + 1)
        dailies = self._activity(user, today, streak)

        week_xp, week_days = self._week_totals(dailies, today)
        self._profile(profile, dailies, streak, today)
        self._weekly_stat(user, today, week_xp, week_days)
        group, size = self._league(user, today, week_xp)
        self._challenges()
        self._claims(user, today)
        checked_in = self._checkin(user, profile, today, opts["checked_in"])

        self._report(user, profile, today, streak, week_xp, group, size, checked_in)

    # ------------------------------------------------------------------ user
    def _user(self, email: str) -> User:
        user, created = User.objects.get_or_create(email=email, defaults={"full_name": DEMO_NAME})
        if created:
            user.set_password(DEMO_PASSWORD)
            user.full_name = user.full_name or DEMO_NAME
            user.save()
        return user

    # -------------------------------------------------------------- activity
    def _activity(self, user, today, streak: int) -> list[DailyActivity]:
        """Chuỗi đang chạy (tính cả hôm nay) + khoảng nghỉ + một chuỗi cũ."""
        plan: list[tuple[object, dict]] = [(today, TODAY_ACTIVITY)]
        for i in range(1, streak):
            plan.append((today - timedelta(days=i), PAST_ACTIVITY[(i - 1) % len(PAST_ACTIVITY)]))

        old_start = streak + GAP_DAYS
        for i, xp in enumerate(OLD_STREAK):
            day = today - timedelta(days=old_start + i)
            plan.append(
                (
                    day,
                    {
                        "xp": xp,
                        "words_reviewed": max(8, xp // 9),
                        "speaking_count": max(3, xp // 22),
                        "listening_count": max(2, xp // 30),
                        "lessons_completed": max(1, xp // 90),
                        "minutes": max(6, xp // 8),
                    },
                )
            )

        # Xoá hoạt động cũ trong khoảng đang gieo để khoảng nghỉ thật là nghỉ.
        oldest = today - timedelta(days=old_start + len(OLD_STREAK) - 1)
        DailyActivity.objects.filter(user=user, date__gte=oldest, date__lte=today).exclude(
            date__in=[d for d, _ in plan]
        ).delete()

        rows = []
        for day, values in plan:
            row, _ = DailyActivity.objects.update_or_create(user=user, date=day, defaults=values)
            rows.append(row)
        return rows

    @staticmethod
    def _week_totals(dailies: list[DailyActivity], today) -> tuple[int, int]:
        monday = today - timedelta(days=today.weekday())
        this_week = [d for d in dailies if monday <= d.date <= today]
        return sum(d.xp for d in this_week), len(this_week)

    def _profile(self, profile, dailies: list[DailyActivity], streak: int, today) -> None:
        profile.xp_total = sum(d.xp for d in dailies)
        profile.level = profile.xp_total // 400 + 1  # learning.services.XP_PER_LEVEL
        profile.coins = COINS
        profile.hearts = HEARTS
        profile.hearts_updated_at = djtz.now()
        profile.streak_current = streak
        profile.streak_best = max(streak, len(OLD_STREAK))
        profile.last_active_date = today
        profile.save(
            update_fields=[
                "xp_total",
                "level",
                "coins",
                "hearts",
                "hearts_updated_at",
                "streak_current",
                "streak_best",
                "last_active_date",
            ]
        )

    @staticmethod
    def _weekly_stat(user, today, week_xp: int, week_days: int) -> None:
        iso = today.isocalendar()
        WeeklyStat.objects.update_or_create(
            user=user,
            iso_year=iso[0],
            iso_week=iso[1],
            defaults={"xp": week_xp, "days_active": week_days},
        )

    # ---------------------------------------------------------------- league
    def _league(self, user, today, week_xp: int) -> tuple[LeagueGroup, int]:
        """Nhóm Kim cương tuần này: 3 người trên demo, phần còn lại dưới -> hạng 4."""
        iso = today.isocalendar()
        iso_year, iso_week = iso[0], iso[1]

        # Rời mọi nhóm khác của tuần này trước khi gán lại (chạy lại vẫn đúng 1 nhóm).
        LeagueMembership.objects.filter(
            user=user, group__iso_year=iso_year, group__iso_week=iso_week
        ).delete()
        group, _ = LeagueGroup.objects.get_or_create(
            tier=LeagueGroup.Tier.DIAMOND, iso_year=iso_year, iso_week=iso_week
        )

        seeded = {user.id}

        def member(email: str, name: str, xp: int) -> None:
            other, created = User.objects.get_or_create(email=email, defaults={"full_name": name})
            if created:
                other.set_unusable_password()
                other.save()
            ensure_profile(other)
            seeded.add(other.id)
            LeagueMembership.objects.update_or_create(
                group=group, user=other, defaults={"xp_week": xp}
            )
            WeeklyStat.objects.update_or_create(
                user=other,
                iso_year=iso_year,
                iso_week=iso_week,
                defaults={"xp": xp, "days_active": min(7, today.weekday() + 1)},
            )

        for email, name, ratio in RIVALS:
            member(email, name, max(1, int(week_xp * ratio)))
        for i in range(FILLER_MEMBERS):
            # 8%..93% XP tuần của demo -> luôn xếp dưới, không phụ thuộc ngày chạy.
            ratio = 0.08 + (i * 17 % 100) / 100 * 0.85
            member(
                f"member{i:02d}@demo.sayfully", f"Học viên {i + 1}", max(1, int(week_xp * ratio))
            )

        LeagueMembership.objects.update_or_create(
            group=group, user=user, defaults={"xp_week": week_xp}
        )
        # Nhóm này có thể còn thành viên của seed khác -> cỡ nhóm sẽ lệch và Top % sai.
        LeagueMembership.objects.filter(group=group).exclude(user_id__in=seeded).delete()
        return group, LeagueMembership.objects.filter(group=group).count()

    # ------------------------------------------------------------- challenges
    def _challenges(self) -> None:
        rows = [(Challenge.Scope.DAILY, c) for c in DAILY_CHALLENGES]
        rows += [(Challenge.Scope.WEEKLY, c) for c in WEEKLY_CHALLENGES]
        for scope, (code, metric, tier, title, desc, target, rx, rc) in rows:
            Challenge.objects.update_or_create(
                code=code,
                defaults={
                    "scope": scope,
                    "metric": metric,
                    "tier": tier,
                    "title_vi": title,
                    "description_vi": desc,
                    "target": target,
                    "reward_xp": rx,
                    "reward_coins": rc,
                    "is_active": True,
                },
            )

    def _claims(self, user, today) -> None:
        """Ghi UserChallenge cho kỳ hiện tại; chỉ CLAIMED_* mới có claimed_at."""
        now = djtz.now()
        for scope, catalog, claimed_codes in (
            (Challenge.Scope.DAILY, DAILY_CHALLENGES, CLAIMED_DAILY),
            (Challenge.Scope.WEEKLY, WEEKLY_CHALLENGES, CLAIMED_WEEKLY),
        ):
            pk = period_key(scope, today)
            codes = [c[0] for c in catalog]
            for ch in Challenge.objects.filter(code__in=codes):
                claimed = ch.code in claimed_codes
                UserChallenge.objects.update_or_create(
                    user=user,
                    challenge=ch,
                    period_key=pk,
                    defaults={
                        "progress": ch.target if claimed else 0,
                        "completed_at": now if claimed else None,
                        "claimed_at": now if claimed else None,
                    },
                )

    # ---------------------------------------------------------------- checkin
    def _checkin(self, user, profile, today, want: bool) -> bool:
        """Điểm danh đọc từ sổ cái xu (reason="checkin") trong ngày, nên gieo/xoá ở đó."""
        start_today = datetime.combine(today, dtime.min, ZoneInfo(profile.timezone))
        CoinTransaction.objects.filter(
            user=user, reason="checkin", created_at__gte=start_today
        ).delete()
        if want:
            CoinTransaction.objects.create(
                user=user,
                amount=CHECKIN_COINS,
                reason="checkin",
                balance_after=profile.coins,
            )
        return want

    # ----------------------------------------------------------------- report
    def _report(self, user, profile, today, streak, week_xp, group, size, checked_in) -> None:
        target = {1: 600, 2: 900, 3: 1200, 4: 1500, 5: 1800}[group.tier]
        done = sum(1 for c in DAILY_CHALLENGES if self._reached(c, today))
        self.stdout.write(
            self.style.SUCCESS(
                f"✔ Màn Thử thách của {user.email}: "
                f"Lv.{profile.level} · {profile.xp_total} XP · {profile.coins} xu · "
                f"{profile.hearts} tim · chuỗi {streak} ngày"
            )
        )
        self.stdout.write(
            f"  Liên đoàn {group.get_tier_display()} {group.iso_year}-W{group.iso_week:02d}: "
            f"{week_xp}/{target} XP ({round(week_xp / target * 100)}%), "
            f"hạng 4/{size} ≈ Top {max(1, round(4 / size * 100))}%"
        )
        self.stdout.write(
            f"  Mục tiêu hôm nay: {TODAY_ACTIVITY['xp']}/{DAILY_GOAL_XP} XP · "
            f"{TODAY_ACTIVITY['words_reviewed']}/{DAILY_GOAL_WORDS} từ · "
            f"{TODAY_ACTIVITY['speaking_count']}/15 câu nói"
        )
        self.stdout.write(
            f"  Nhiệm vụ ngày: {done}/{len(DAILY_CHALLENGES)} đạt, "
            f"{len(CLAIMED_DAILY)} đã nhận thưởng · "
            f"điểm danh: {'đã điểm danh' if checked_in else 'chưa (nút còn bấm được)'}"
        )
        self.stdout.write(
            "  Kiểm tra: GET /api/v1/challenges/overview "
            f"(đăng nhập {user.email} / {DEMO_PASSWORD})"
        )
        self.stdout.write(
            self.style.WARNING("  Lưu ý: chạy `seed_demo` sau lệnh này sẽ ghi đè lại số nhỏ hơn.")
        )

    @staticmethod
    def _reached(challenge: tuple, today) -> bool:
        _code, metric, _tier, _title, _desc, target, _rx, _rc = challenge
        field = {
            "xp": "xp",
            "words": "words_reviewed",
            "lessons": "lessons_completed",
            "speaking": "speaking_count",
        }.get(metric)
        if metric == "days":
            return target <= 1
        return field is not None and TODAY_ACTIVITY[field] >= target
