from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone
from django_q.models import Schedule

from apps.accounts import services
from apps.accounts.models import User, UserProfile
from apps.accounts.tasks import purge_deleted_accounts


def _delete(user, days_ago):
    services.soft_delete_account(user)
    User.objects.filter(pk=user.pk).update(deleted_at=timezone.now() - timedelta(days=days_ago))


@pytest.mark.django_db
def test_purges_only_accounts_deleted_over_30_days_ago(user):
    services.ensure_profile(user)
    recent = User.objects.create_user(email="moi@example.com", password="MatKhauRatManh123")
    active = User.objects.create_user(email="con@example.com", password="MatKhauRatManh123")
    _delete(user, days_ago=31)
    _delete(recent, days_ago=29)

    assert purge_deleted_accounts() == 1
    assert not User.objects.filter(pk=user.pk).exists()
    assert not UserProfile.objects.filter(user_id=user.pk).exists()
    assert User.objects.filter(pk__in=[recent.pk, active.pk]).count() == 2


@pytest.mark.django_db
def test_command_and_daily_schedule(user, capsys):
    _delete(user, days_ago=40)
    call_command("purge_deleted_accounts")
    assert "Đã xoá cứng 1 tài khoản" in capsys.readouterr().out
    schedule = Schedule.objects.get(name="purge-deleted-accounts")
    assert (schedule.func, schedule.schedule_type, schedule.repeats) == (
        "apps.accounts.tasks.purge_deleted_accounts",
        Schedule.DAILY,
        -1,
    )
