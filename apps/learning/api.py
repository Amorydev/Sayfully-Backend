"""G4 lõi học tập — chunk vòng học: /home, /learn/path, lesson start/complete/progress.

Mọi thay đổi XP/xu/tim/streak đi qua `services.record`. `complete` idempotent (gọi lại
không cộng đôi). Chi tiết A2–C2 cần Premium; bài khoá theo lộ trình → `lesson_locked`.
"""

from datetime import datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone as djtz
from ninja import Query, Router

from apps.accounts.services import ensure_profile
from apps.common.exceptions import Forbidden, NotFound
from apps.common.schemas import ErrorOut
from apps.content.models import Lesson, Unit
from apps.gamification.models import Badge, UserBadge
from apps.notifications.models import Notification

from . import schemas as s
from . import services
from .models import DailyActivity, LessonProgress, SRSCard, SRSReviewLog

router = Router()

_WEEKDAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
XP_PER_REVIEW = 2


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


def _syllables(v) -> list[s.SyllableOut]:
    return [
        s.SyllableOut(
            text=t, is_primary=(i == v.primary_stress), is_secondary=(i == v.secondary_stress)
        )
        for i, t in enumerate(v.ipa_syllables or [])
    ]


def _review_card(card: SRSCard, accent: str) -> s.ReviewCardOut:
    v = card.vocabulary
    return s.ReviewCardOut(
        vocab_id=v.id,
        headword=v.headword,
        pos=v.pos,
        level=v.level_id,
        ipa=v.ipa_us if accent == "US" else v.ipa_uk,
        syllables=_syllables(v),
        meaning_vi=v.meaning_vi,
        definition_en=v.definition_en,
        audio_uk_url=_media(v.audio_uk_path),
        audio_us_url=_media(v.audio_us_path),
        examples=[
            s.ExampleOut(text_en=e.text_en, text_vi=e.text_vi, audio_url=_media(e.audio_path))
            for e in v.examples.all()
        ],
        collocations=[
            s.CollocationOut(text_en=c.text_en, meaning_vi=c.meaning_vi)
            for c in v.collocations.all()
        ],
        word_family=[w.headword for w in v.word_family.all()],
        due_at=card.due_at,
        state=card.state,
    )


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


# =============================================================== SRS review (FSRS)
@router.get(
    "/learn/review/due",
    response={200: list[s.ReviewCardOut], 401: ErrorOut},
    summary="Từ đến hạn ôn tập",
    description="Thẻ SRS đến hạn (bỏ thẻ tạm dừng), sớm nhất trước. Nuôi màn ôn tập / flashcard.",
)
def review_due(request, limit: int = Query(20, ge=1, le=100)):
    user = request.auth
    profile = ensure_profile(user)
    cards = (
        SRSCard.objects.filter(user=user, due_at__lte=djtz.now())
        .exclude(state=SRSCard.State.SUSPENDED)
        .select_related("vocabulary")
        .prefetch_related(
            "vocabulary__examples", "vocabulary__collocations", "vocabulary__word_family"
        )
        .order_by("due_at")[:limit]
    )
    return [_review_card(c, profile.accent) for c in cards]


@router.post(
    "/learn/review",
    response={200: s.ReviewResultOut, 401: ErrorOut, 422: ErrorOut},
    summary="Nộp kết quả ôn tập (theo lô)",
    description="Cập nhật lịch FSRS cho từng thẻ, ghi nhật ký, cộng XP theo số từ đã ôn.",
)
def submit_review(request, payload: list[s.ReviewItemIn]):
    user = request.auth
    profile = ensure_profile(user)
    now = djtz.now()
    cards_map = {
        c.vocabulary_id: c
        for c in SRSCard.objects.filter(user=user, vocabulary_id__in=[i.vocab_id for i in payload])
    }
    results = []
    with transaction.atomic():
        for item in payload:
            card = cards_map.get(item.vocab_id)
            if card is None:
                continue
            state_before = services.review_srs_card(card, item.rating, now)
            SRSReviewLog.objects.create(
                user=user,
                vocabulary_id=item.vocab_id,
                rating=item.rating,
                state_before=state_before,
            )
            results.append(
                s.ReviewCardResultOut(vocab_id=item.vocab_id, state=card.state, due_at=card.due_at)
            )
        n = len(results)
        reward = services.record(profile, xp=XP_PER_REVIEW * n, words=n, minutes=0) if n else None
    return s.ReviewResultOut(
        reviewed=n,
        xp_earned=reward.xp_earned if reward else 0,
        streak_days=reward.streak_days if reward else profile.streak_current,
        cards=results,
    )


@router.get(
    "/learn/review/stats",
    response={200: s.ReviewStatsOut, 401: ErrorOut},
    summary="Thống kê ôn tập",
    description="Đã học / đã vững / đang học / đến hạn hôm nay / đã ôn hôm nay / tỷ lệ nhớ 30 ngày.",
)
def review_stats(request):
    user = request.auth
    profile = ensure_profile(user)
    now = djtz.now()
    today = services.local_today(profile)
    tz = ZoneInfo(profile.timezone)
    start_today = datetime.combine(today, dtime.min, tz)
    end_today = datetime.combine(today, dtime.max, tz)

    cards = SRSCard.objects.filter(user=user)
    studied = cards.count()
    mastered = cards.filter(state=SRSCard.State.REVIEW).count()
    due_today = cards.filter(due_at__lte=end_today).exclude(state=SRSCard.State.SUSPENDED).count()
    reviewed_today = SRSReviewLog.objects.filter(user=user, reviewed_at__gte=start_today).count()
    logs30 = SRSReviewLog.objects.filter(user=user, reviewed_at__gte=now - timedelta(days=30))
    total = logs30.count()
    good = logs30.filter(rating__gte=3).count()
    return s.ReviewStatsOut(
        studied=studied,
        mastered=mastered,
        learning=studied - mastered,
        due_today=due_today,
        reviewed_today=reviewed_today,
        retention_percent=round(good / total * 100) if total else 0,
    )
