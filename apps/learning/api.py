"""G4 lõi học tập — chunk vòng học: /home, /learn/path, lesson start/complete/progress.

Mọi thay đổi XP/xu/tim/streak đi qua `services.record`. `complete` idempotent (gọi lại
không cộng đôi). Chi tiết A2–C2 cần Premium; bài khoá theo lộ trình → `lesson_locked`.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone as djtz
from ninja import Router

from apps.accounts.services import ensure_profile
from apps.common.exceptions import Forbidden, NotFound
from apps.common.schemas import ErrorOut
from apps.content.models import Lesson, Unit
from apps.gamification.models import Badge, UserBadge
from apps.notifications.models import Notification

from . import schemas as s
from . import services
from .models import DailyActivity, LessonProgress, SRSCard

router = Router()

_WEEKDAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]


def _media(path: str | None) -> str | None:
    return f"{settings.R2_PUBLIC_BASE.rstrip('/')}/{path}" if path else None


def _gate(profile, level) -> None:
    if not level.is_free and not profile.is_premium:
        raise Forbidden("Nội dung này dành cho Premium", code="premium_required")


def _is_unlocked(user, lesson: Lesson) -> bool:
    if lesson.order <= 1:
        return True
    prev = Lesson.objects.filter(unit=lesson.unit, order=lesson.order - 1).first()
    if prev is None:
        return True
    return LessonProgress.objects.filter(
        user=user, lesson=prev, status=LessonProgress.Status.COMPLETED
    ).exists()


def _stars(correct: int, total: int) -> int:
    if total <= 0:
        return 0
    ratio = correct / total
    return 3 if ratio >= 1 else (2 if ratio >= 0.8 else 1)


def _week_progress(user, today) -> list[s.DayProgressOut]:
    monday = today - timedelta(days=today.weekday())
    active = set(
        DailyActivity.objects.filter(
            user=user, date__gte=monday, date__lte=monday + timedelta(days=6)
        ).values_list("date", flat=True)
    )
    out = []
    for i, label in enumerate(_WEEKDAYS):
        d = monday + timedelta(days=i)
        out.append(s.DayProgressOut(label=label, active=d in active, is_today=d == today))
    return out


def _milestone(user, streak: int) -> s.MilestoneOut | None:
    earned = set(UserBadge.objects.filter(user=user).values_list("badge_id", flat=True))
    best = None
    for b in Badge.objects.all():
        cond = b.condition or {}
        if cond.get("metric") != "streak" or b.id in earned:
            continue
        value = int(cond.get("value", 0))
        if value > streak and (best is None or value < best[0]):
            best = (value, b.title_vi)
    if best is None:
        return None
    return s.MilestoneOut(name=best[1], target_days=best[0], days_left=best[0] - streak)


def _key_vocab(lesson: Lesson, accent: str) -> list[s.KeyVocabOut]:
    out = []
    for step in lesson.steps.filter(kind="vocab").select_related("vocabulary"):
        v = step.vocabulary
        if v is None:
            continue
        out.append(
            s.KeyVocabOut(
                id=v.id,
                headword=v.headword,
                ipa=v.ipa_us if accent == "US" else v.ipa_uk,
                meaning_vi=v.meaning_vi,
            )
        )
    return out


# =============================================================== /home
@router.get(
    "/home",
    response={200: s.HomeOut, 401: ErrorOut},
    summary="Dữ liệu trang chủ (1 lần gọi)",
    description="Hồ sơ tóm tắt, mục tiêu ngày, bài đang học, số từ đến hạn, thông báo chưa đọc.",
)
def home(request):
    user = request.auth
    profile = ensure_profile(user)
    services.regen_hearts(profile)
    today = services.local_today(profile)

    daily = DailyActivity.objects.filter(user=user, date=today).first()
    words_done = daily.words_reviewed if daily else 0
    minutes = daily.minutes if daily else 0
    xp_today = daily.xp if daily else 0
    words_target = profile.daily_goal_words or 1
    goal = s.DailyGoalOut(
        words_done=words_done,
        words_target=profile.daily_goal_words,
        minutes=minutes,
        xp=xp_today,
        xp_target=profile.daily_goal_xp,
        percent=min(100, round(words_done / words_target * 100)),
    )

    lp = (
        LessonProgress.objects.filter(user=user, status=LessonProgress.Status.IN_PROGRESS)
        .select_related("lesson__unit__level")
        .order_by("-updated_at")
        .first()
    )
    current = None
    if lp:
        total_steps = lp.lesson.steps.count() or 1
        percent = min(100, round(lp.step_index / total_steps * 100))
        current = s.CurrentLessonOut(
            code=lp.lesson.code,
            level=lp.lesson.unit.level_id,
            unit_title=lp.lesson.unit.title_vi,
            title_vi=lp.lesson.title_vi,
            percent=percent,
            minutes_left=max(0, round(lp.lesson.est_minutes * (1 - percent / 100))),
        )

    due_count = SRSCard.objects.filter(user=user, due_at__lte=djtz.now()).exclude(state=4).count()
    unread = Notification.objects.filter(user=user, read_at__isnull=True).count()

    return s.HomeOut(
        profile=s.HomeProfileOut(
            name=user.full_name,
            avatar_url=_media(user.avatar_path),
            cefr_level=profile.cefr_level,
            level=profile.level,
            level_label="Học viên",
            xp=profile.xp_total,
            coins=profile.coins,
            hearts=profile.hearts,
            streak_days=profile.streak_current,
            is_premium=profile.is_premium,
        ),
        unread_notifications=unread,
        due_review_count=due_count,
        daily_goal=goal,
        current_lesson=current,
        challenges=s.HomeChallengesOut(done=0, total=0, reward_coins=0, items=[]),
        rank=None,
    )


# =============================================================== /learn/path
@router.get(
    "/learn/path",
    response={200: s.PathOut, 401: ErrorOut, 404: ErrorOut},
    summary="Lộ trình học của một cấp (nội dung + tiến độ)",
    description="Unit + bài kèm trạng thái, sao, khoá — trộn sẵn tiến độ người dùng.",
)
def learn_path(request, level: str):
    user = request.auth
    ensure_profile(user)
    units = (
        Unit.objects.filter(level_id=level.upper()).prefetch_related("lessons").order_by("order")
    )
    if not units:
        raise NotFound("Không tìm thấy cấp học")

    progress = {
        p.lesson_id: p
        for p in LessonProgress.objects.filter(user=user, lesson__unit__level_id=level.upper())
    }
    out_units = []
    for unit in units:
        lessons = list(unit.lessons.order_by("order"))
        done = 0
        lesson_outs = []
        for ls in lessons:
            p = progress.get(ls.id)
            status = p.status if p else "not_started"
            if status == LessonProgress.Status.COMPLETED:
                done += 1
            lesson_outs.append(
                s.PathLessonOut(
                    id=ls.id,
                    code=ls.code,
                    order=ls.order,
                    title_vi=ls.title_vi,
                    est_minutes=ls.est_minutes,
                    xp_reward=ls.xp_reward,
                    status=status,
                    stars=p.stars if p else 0,
                    is_locked=not _is_unlocked(user, ls),
                )
            )
        out_units.append(
            s.PathUnitOut(
                id=unit.id,
                order=unit.order,
                code=unit.code,
                title_vi=unit.title_vi,
                title_en=unit.title_en,
                reward=unit.reward or {},
                lesson_count=len(lessons),
                done_count=done,
                lessons=lesson_outs,
            )
        )
    return s.PathOut(level=level.upper(), units=out_units)


# =============================================================== lesson flow
def _get_lesson(code: str) -> Lesson:
    lesson = Lesson.objects.filter(code=code).select_related("unit__level").first()
    if lesson is None:
        raise NotFound("Không tìm thấy bài học")
    return lesson


def _progress_out(lesson: Lesson, p: LessonProgress) -> s.LessonProgressOut:
    return s.LessonProgressOut(
        code=lesson.code,
        status=p.status,
        step_index=p.step_index,
        correct_count=p.correct_count,
        total_questions=p.total_questions,
        stars=p.stars,
        xp_earned=p.xp_earned,
        completed_at=p.completed_at,
    )


@router.post(
    "/learn/lessons/{code}/start",
    response={200: s.LessonProgressOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Bắt đầu bài học",
    description="Tạo/lấy tiến độ bài. Cấp A2–C2 cần Premium; bài chưa mở khoá → `lesson_locked`.",
)
def start_lesson(request, code: str):
    user = request.auth
    profile = ensure_profile(user)
    lesson = _get_lesson(code)
    _gate(profile, lesson.unit.level)
    if not _is_unlocked(user, lesson):
        raise Forbidden("Bài học chưa mở khoá", code="lesson_locked")
    p, _ = LessonProgress.objects.get_or_create(user=user, lesson=lesson)
    return _progress_out(lesson, p)


@router.get(
    "/learn/lessons/{code}/progress",
    response={200: s.LessonProgressOut, 401: ErrorOut, 404: ErrorOut},
    summary="Tiến độ một bài học",
    description="Trạng thái/step/sao của bài (mặc định not_started nếu chưa bắt đầu).",
)
def lesson_progress(request, code: str):
    user = request.auth
    ensure_profile(user)
    lesson = _get_lesson(code)
    p = LessonProgress.objects.filter(user=user, lesson=lesson).first()
    if p is None:
        return s.LessonProgressOut(
            code=lesson.code,
            status="not_started",
            step_index=0,
            correct_count=0,
            total_questions=0,
            stars=0,
            xp_earned=0,
            completed_at=None,
        )
    return _progress_out(lesson, p)


@router.post(
    "/learn/lessons/{code}/complete",
    response={200: s.LessonResultOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Hoàn thành bài học (idempotent)",
    description=(
        "Chấm sao, cộng XP/xu/streak, tạo thẻ SRS cho từ của bài — trong 1 transaction. "
        "Gọi lại KHÔNG cộng đôi (trả kết quả không thưởng thêm)."
    ),
)
def complete_lesson(request, code: str, payload: s.LessonCompleteIn):
    user = request.auth
    profile = ensure_profile(user)
    lesson = _get_lesson(code)
    _gate(profile, lesson.unit.level)

    total = payload.total
    correct = payload.correct_count
    duration = payload.duration_sec

    today = services.local_today(profile)
    p = LessonProgress.objects.filter(user=user, lesson=lesson).first()
    next_lesson = (
        Lesson.objects.filter(unit=lesson.unit, order=lesson.order + 1)
        .values_list("code", flat=True)
        .first()
    )

    if p and p.status == LessonProgress.Status.COMPLETED:
        return s.LessonResultOut(
            code=lesson.code,
            percent=100,
            correct_count=p.correct_count,
            total=p.total_questions,
            stars=p.stars,
            xp_earned=0,
            coins_earned=0,
            streak_days=profile.streak_current,
            is_streak_record=False,
            leveled_up=False,
            level=profile.level,
            week_progress=_week_progress(user, today),
            milestone=_milestone(user, profile.streak_current),
            key_vocab=_key_vocab(lesson, profile.accent),
            srs_cards_created=0,
            next_lesson_code=next_lesson,
        )

    stars = _stars(correct, total)
    with transaction.atomic():
        p, _ = LessonProgress.objects.get_or_create(user=user, lesson=lesson)
        p.status = LessonProgress.Status.COMPLETED
        p.correct_count = correct
        p.total_questions = total
        p.stars = stars
        p.xp_earned = lesson.xp_reward
        p.completed_at = djtz.now()
        p.save()
        reward = services.record(
            profile,
            xp=lesson.xp_reward,
            coins=5,
            coin_reason="lesson",
            ref_type="lesson",
            ref_id=lesson.code,
            lessons=1,
            minutes=round(duration / 60),
        )
        vocab_ids = list(
            lesson.steps.filter(kind="vocab", vocabulary__isnull=False).values_list(
                "vocabulary_id", flat=True
            )
        )
        srs_created = services.create_srs_cards(user, vocab_ids)

    return s.LessonResultOut(
        code=lesson.code,
        percent=100,
        correct_count=correct,
        total=total,
        stars=stars,
        xp_earned=reward.xp_earned,
        coins_earned=reward.coins_earned,
        streak_days=reward.streak_days,
        is_streak_record=reward.is_streak_record,
        leveled_up=reward.leveled_up,
        level=reward.level,
        week_progress=_week_progress(user, today),
        milestone=_milestone(user, reward.streak_days),
        key_vocab=_key_vocab(lesson, profile.accent),
        srs_cards_created=srs_created,
        next_lesson_code=next_lesson,
    )
