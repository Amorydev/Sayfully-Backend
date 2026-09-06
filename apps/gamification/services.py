"""Game hoá — tiến độ thử thách tính từ DailyActivity/WeeklyStat (không lưu tăng dần),
huy hiệu mở khoá lười khi đọc.
"""

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone as djtz

from apps.learning.models import LessonProgress, WeeklyStat

from .models import Badge, LeagueGroup, LeagueMembership, UserBadge

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


LEAGUE_SIZE = 30


def current_week():
    iso = djtz.now().isocalendar()
    return iso[0], iso[1]


def ensure_league_membership(user):
    y, w = current_week()
    m = (
        LeagueMembership.objects.filter(user=user, group__iso_year=y, group__iso_week=w)
        .select_related("group")
        .first()
    )
    if m:
        return m
    group = (
        LeagueGroup.objects.filter(iso_year=y, iso_week=w, tier=LeagueGroup.Tier.BRONZE)
        .annotate(n=Count("members"))
        .filter(n__lt=LEAGUE_SIZE)
        .order_by("id")
        .first()
    )
    if group is None:
        group = LeagueGroup.objects.create(tier=LeagueGroup.Tier.BRONZE, iso_year=y, iso_week=w)
    xp0 = (
        WeeklyStat.objects.filter(user=user, iso_year=y, iso_week=w)
        .values_list("xp", flat=True)
        .first()
        or 0
    )
    return LeagueMembership.objects.create(group=group, user=user, xp_week=xp0)


def league_rank(user):
    """Bậc liên đoàn + hạng hiện tại của user trong tuần này.

    Hạng tính trực tiếp từ XP tuần (WeeklyStat) trong nhóm, không đợi chốt cuối tuần.
    """
    m = ensure_league_membership(user)
    group = m.group
    member_ids = list(
        LeagueMembership.objects.filter(group=group).values_list("user_id", flat=True)
    )
    xp_map = dict(
        WeeklyStat.objects.filter(
            iso_year=group.iso_year, iso_week=group.iso_week, user_id__in=member_ids
        ).values_list("user_id", "xp")
    )
    ranked = sorted(member_ids, key=lambda uid: -xp_map.get(uid, 0))
    rank = next((i + 1 for i, uid in enumerate(ranked) if uid == user.id), 0)
    return group, rank, xp_map.get(user.id, 0)
