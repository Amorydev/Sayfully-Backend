"""Job nền của tài khoản — chạy qua django-q (lịch tạo ở migration 0009)."""

import logging
from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import User

log = logging.getLogger(__name__)

PURGE_AFTER = timedelta(days=30)


def purge_deleted_accounts() -> int:
    """Xoá cứng tài khoản đã xoá mềm quá 30 ngày; dữ liệu học đi theo nhờ CASCADE."""
    cutoff = timezone.now() - PURGE_AFTER
    stale = User.objects.filter(deleted_at__isnull=False, deleted_at__lte=cutoff)
    count = stale.count()
    if count:
        stale.delete()
        log.info("Đã xoá cứng %s tài khoản quá hạn", count)
    return count
