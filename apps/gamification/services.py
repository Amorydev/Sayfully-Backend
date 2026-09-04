"""Game hoá — tiến độ thử thách tính từ DailyActivity/WeeklyStat (không lưu tăng dần),
huy hiệu mở khoá lười khi đọc.
"""

from datetime import timedelta

from apps.learning.models import LessonProgress

from .models import Badge, UserBadge

_DAILY_FIELD = {
    "xp": "xp",
    "words": "words_reviewed",
    "lessons": "lessons_completed",
    "speaking": "speaking_count",
}


def period_key(scope: str, today) -> str:
    if scope == "daily":
        return today.isoformat()
    iso = today.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def challenge_progress(challenge, dailies: list) -> int:
    """`dailies`: DailyActivity của hôm nay (daily) hoặc cả tuần (weekly)."""
    if challenge.metric == "days":
        return len([d for d in dailies if d.xp > 0 or d.lessons_completed > 0])
    field = _DAILY_FIELD.get(challenge.metric)
    if field is None:
        return 0
    return sum(getattr(d, field) for d in dailies)


def week_range(today):
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


def check_badges(user, profile) -> None:
    """Mở khoá lười các huy hiệu đủ điều kiện (streak/xp/level/lessons)."""
    earned = set(UserBadge.objects.filter(user=user).values_list("badge_id", flat=True))
    lessons_done = LessonProgress.objects.filter(
        user=user, status=LessonProgress.Status.COMPLETED
    ).count()
    stats = {
        "streak": profile.streak_best,
        "xp": profile.xp_total,
        "level": profile.level,
        "lessons": lessons_done,
    }
    for badge in Badge.objects.all():
        if badge.id in earned:
            continue
        cond = badge.condition or {}
        metric = cond.get("metric")
        value = int(cond.get("value", 0))
        if metric in stats and stats[metric] >= value:
            UserBadge.objects.get_or_create(user=user, badge=badge)
