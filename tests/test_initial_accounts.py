import pytest
from django.core.management import call_command
from django.test import RequestFactory

from apps.accounts.models import User
from apps.accounts.services import authenticate_password
from apps.gamification.api import leaderboard
from apps.gamification.models import LeagueMembership, UserCosmetic, UserBadge
from apps.learning.models import DailyActivity, WeeklyStat


@pytest.mark.django_db
class TestSeedInitialAccounts:
    def test_seed_command_creates_ten_accounts(self):
        call_command("seed_initial_accounts")

        assert User.objects.count() >= 10
        users = User.objects.filter(email__endswith="@sayfully.app")
        assert users.count() == 10

        # Kiểm tra tài khoản top 1
        top1 = User.objects.get(email="hoang.minh@sayfully.app")
        assert top1.full_name == "Hoàng Minh"
        assert top1.avatar_path.startswith("https://")
        assert top1.profile.level == 9
        assert top1.profile.cefr_level == "B2"
        assert top1.profile.streak_current == 42
        assert top1.profile.avatar_frame == "frame_imperial"
        assert top1.profile.is_premium is True

        # Kiểm tra quyền sở hữu khung avatar
        assert UserCosmetic.objects.filter(user=top1, item__code="frame_imperial").exists()

        # Kiểm tra huy hiệu
        assert UserBadge.objects.filter(user=top1, badge__code="streak30").exists()
        assert UserBadge.objects.filter(user=top1, badge__code="level5").exists()

        # Kiểm tra hoạt động hằng ngày và tuần
        assert DailyActivity.objects.filter(user=top1).count() == 7
        assert WeeklyStat.objects.filter(user=top1).exists()

    def test_seed_command_is_idempotent(self):
        call_command("seed_initial_accounts")
        call_command("seed_initial_accounts")

        users = User.objects.filter(email__endswith="@sayfully.app")
        assert users.count() == 10

    def test_seed_accounts_can_login(self):
        call_command("seed_initial_accounts", password="TestSecret@123")

        user = authenticate_password("bao.tran@sayfully.app", "TestSecret@123")
        assert user.full_name == "Bảo Trân"
        assert user.profile.avatar_frame == "frame_dragon"

    def test_leaderboard_includes_seeded_accounts_with_podium(self):
        call_command("seed_initial_accounts")

        user = User.objects.get(email="hoang.minh@sayfully.app")
        rf = RequestFactory()
        req = rf.get("/api/gamification/leaderboard?scope=league&period=week")
        req.auth = user

        res = leaderboard(req, scope="league", period="week")
        assert res.scope == "league"
        assert len(res.entries) >= 10

        # Top 1 bục vinh danh
        assert res.entries[0].rank == 1
        assert res.entries[0].name == "Hoàng Minh"
        assert res.entries[0].avatar_frame == "frame_imperial"
        assert res.entries[0].xp_week == 2680
        assert res.entries[0].avatar_url.startswith("https://")

        # Top 2
        assert res.entries[1].rank == 2
        assert res.entries[1].name == "Bảo Trân"
        assert res.entries[1].avatar_frame == "frame_dragon"
        assert res.entries[1].xp_week == 2240

        # Top 3
        assert res.entries[2].rank == 3
        assert res.entries[2].name == "Khánh Linh"
        assert res.entries[2].avatar_frame == "frame_aurora"
        assert res.entries[2].xp_week == 1890
