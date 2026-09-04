"""Lõi thưởng — MỌI thay đổi XP/xu/tim/streak/level đi qua đây. G6/G8 tái dùng.

Ngày tính theo `UserProfile.timezone` (không UTC). Tim hồi lười lúc đọc.
"""

from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone as djtz
from fsrs import Card as FsrsCard
from fsrs import Rating, Scheduler

from apps.accounts.models import UserProfile
from apps.gamification.models import CoinTransaction

from .models import DailyActivity, SRSCard

_scheduler = Scheduler()

XP_PER_LEVEL = 400
HEARTS_MAX = 5
HEART_REGEN_MINUTES = 30


def level_for_xp(xp: int) -> int:
    return xp // XP_PER_LEVEL + 1


def local_today(profile: UserProfile):
    return djtz.now().astimezone(ZoneInfo(profile.timezone)).date()


def regen_hearts(profile: UserProfile) -> None:
    """Hồi tim theo thời gian trôi kể từ `hearts_updated_at`. Gọi khi đọc."""
    if profile.hearts >= HEARTS_MAX:
        return
    elapsed = djtz.now() - profile.hearts_updated_at
    gained = int(elapsed.total_seconds() // (HEART_REGEN_MINUTES * 60))
    if gained <= 0:
        return
    new_hearts = min(HEARTS_MAX, profile.hearts + gained)
    if new_hearts == HEARTS_MAX:
        profile.hearts_updated_at = djtz.now()
    else:
        profile.hearts_updated_at += timedelta(minutes=HEART_REGEN_MINUTES * gained)
    profile.hearts = new_hearts
    profile.save(update_fields=["hearts", "hearts_updated_at"])


@dataclass
class RewardResult:
    xp_earned: int
    coins_earned: int
    level: int
    leveled_up: bool
    streak_days: int
    is_streak_record: bool


def _bump_streak(profile: UserProfile, today) -> bool:
    """Cập nhật streak khi có hoạt động ĐẦU TIÊN trong ngày. Trả về có phá kỷ lục không."""
    prev = (
        DailyActivity.objects.filter(user=profile.user, date__lt=today)
        .order_by("-date")
        .values_list("date", flat=True)
        .first()
    )
    if prev == today - timedelta(days=1):
        profile.streak_current += 1
    elif prev == today - timedelta(days=2) and profile.streak_freezes > 0:
        profile.streak_freezes -= 1
        profile.streak_current += 1
    else:
        profile.streak_current = 1
    record = profile.streak_current > profile.streak_best
    profile.streak_best = max(profile.streak_best, profile.streak_current)
    return record


def record(
    profile: UserProfile,
    *,
    xp: int = 0,
    coins: int = 0,
    coin_reason: str = "",
    ref_type: str = "",
    ref_id: str = "",
    lessons: int = 0,
    words: int = 0,
    speaking: int = 0,
    minutes: int = 0,
) -> RewardResult:
    """Ghi 1 lần hoạt động: DailyActivity + streak + XP/level + xu (kèm sổ cái)."""
    today = local_today(profile)
    first_today = not DailyActivity.objects.filter(user=profile.user, date=today).exists()

    daily, _ = DailyActivity.objects.get_or_create(user=profile.user, date=today)
    daily.xp += xp
    daily.lessons_completed += lessons
    daily.words_reviewed += words
    daily.speaking_count += speaking
    daily.minutes += minutes
    daily.save()

    is_record = _bump_streak(profile, today) if first_today else False

    before_level = profile.level
    profile.xp_total += xp
    profile.level = level_for_xp(profile.xp_total)
    if coins:
        profile.coins += coins
    profile.save(
        update_fields=[
            "xp_total",
            "level",
            "coins",
            "streak_current",
            "streak_best",
            "streak_freezes",
        ]
    )
    if coins:
        CoinTransaction.objects.create(
            user=profile.user,
            amount=coins,
            reason=coin_reason,
            ref_type=ref_type,
            ref_id=str(ref_id),
            balance_after=profile.coins,
        )

    return RewardResult(
        xp_earned=xp,
        coins_earned=coins,
        level=profile.level,
        leveled_up=profile.level > before_level,
        streak_days=profile.streak_current,
        is_streak_record=is_record,
    )


def review_srs_card(card: SRSCard, rating: int, now) -> int:
    """Cập nhật thẻ theo FSRS. Trả về state trước khi ôn (để đếm lapse)."""
    if card.reps == 0 or card.state == SRSCard.State.NEW:
        fcard = FsrsCard()
    else:
        fcard = FsrsCard.from_dict(
            {
                "card_id": card.id,
                "state": int(card.state),
                "step": card.fsrs_step,
                "stability": card.stability or None,
                "difficulty": card.difficulty or None,
                "due": card.due_at.isoformat(),
                "last_review": (
                    card.last_reviewed_at.isoformat() if card.last_reviewed_at else None
                ),
            }
        )
    state_before = int(card.state)
    new, _ = _scheduler.review_card(fcard, Rating(rating), review_datetime=now)
    card.state = int(new.state)
    card.fsrs_step = new.step or 0
    card.stability = new.stability or 0.0
    card.difficulty = new.difficulty or 0.0
    card.due_at = new.due
    card.last_reviewed_at = now
    card.reps += 1
    if rating == Rating.Again and state_before == SRSCard.State.REVIEW:
        card.lapses += 1
    card.save(
        update_fields=[
            "state",
            "fsrs_step",
            "stability",
            "difficulty",
            "due_at",
            "last_reviewed_at",
            "reps",
            "lapses",
        ]
    )
    return state_before


def create_srs_cards(user, vocab_ids) -> int:
    """Tạo thẻ SRS trạng thái NEW cho các từ của bài. Idempotent theo (user, vocab)."""
    now = djtz.now()
    created = 0
    for vid in vocab_ids:
        _, was_created = SRSCard.objects.get_or_create(
            user=user, vocabulary_id=vid, defaults={"due_at": now}
        )
        created += was_created
    return created
