"""G4 lõi học tập — chunk vòng học: /home, /learn/path, lesson start/complete/progress.

Mọi thay đổi XP/xu/tim/streak đi qua `services.record`. `complete` idempotent (gọi lại
không cộng đôi). Chi tiết A2–C2 cần Premium; bài khoá theo lộ trình → `lesson_locked`.
"""

from datetime import date, datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone as djtz
from ninja import File, Query, Router
from ninja.files import UploadedFile

from apps.accounts.services import ensure_profile
from apps.ai.models import RoleplayScenario
from apps.common.exceptions import AppError, Forbidden, NotFound
from apps.common.schemas import ErrorOut
from apps.content.models import (
    Dialogue,
    GrammarPoint,
    IPASound,
    Lesson,
    Level,
    LevelMilestone,
    Reading,
    ShadowingDeck,
    Story,
    Topic,
    Unit,
    Video,
    Vocabulary,
)
from apps.content.schemas import Page
from apps.gamification.models import (
    Badge,
    Challenge,
    CoinTransaction,
    Game,
    UserBadge,
    UserChallenge,
)
from apps.notifications.models import Notification

from . import schemas as s
from . import services
from .models import (
    DailyActivity,
    LessonProgress,
    NotebookEntry,
    PlacementAttempt,
    PlacementQuestion,
    SRSCard,
    SRSReviewLog,
    UserSkill,
)

_CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]
_AVATAR_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_AVATAR_MAX = 5 * 1024 * 1024


def upload_avatar(key: str, data: bytes, content_type: str) -> str:
    import boto3  # noqa: PLC0415

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )
    client.put_object(Bucket=settings.R2_BUCKET, Key=key, Body=data, ContentType=content_type)
    return key

router = Router()

_WEEKDAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
XP_PER_REVIEW = 2
NOTEBOOK_LIMITS = {False: 100, True: 4000}  # free / premium


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

    daily_challenges = list(
        Challenge.objects.filter(scope=Challenge.Scope.DAILY, is_active=True).order_by("tier", "id")
    )
    progress_by_id = dict(
        UserChallenge.objects.filter(
            user=user, period_key=today.isoformat(), challenge__in=daily_challenges
        ).values_list("challenge_id", "progress")
    )
    challenge_items = []
    challenges_done = 0
    challenges_reward = 0
    for ch in daily_challenges:
        cur = progress_by_id.get(ch.id, 0)
        if cur >= ch.target:
            challenges_done += 1
        challenges_reward += ch.reward_coins
        challenge_items.append(
            s.HomeChallengeOut(
                id=ch.id,
                title=ch.title_vi,
                current=min(cur, ch.target),
                target=ch.target,
                reward_coins=ch.reward_coins,
            )
        )

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
        challenges=s.HomeChallengesOut(
            done=challenges_done,
            total=len(daily_challenges),
            reward_coins=challenges_reward,
            items=challenge_items,
        ),
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
    level_obj = Level.objects.filter(code=level.upper()).first()
    if level_obj is None:
        raise NotFound("Không tìm thấy cấp học")

    units = (
        Unit.objects.filter(level_id=level.upper()).prefetch_related("lessons").order_by("order")
    )

    progress = {
        p.lesson_id: p
        for p in LessonProgress.objects.filter(user=user, lesson__unit__level_id=level.upper())
    }
    out_units = []
    prev_completed = True  # unit đầu luôn mở; unit sau mở khi unit trước xong hết bài
    xp_earned = 0
    xp_target = 0
    lessons_total = 0
    for unit in units:
        lessons = list(unit.lessons.order_by("order"))
        lessons_total += len(lessons)
        unit_locked = not prev_completed
        done = 0
        lesson_outs = []
        for ls in lessons:
            p = progress.get(ls.id)
            status = p.status if p else "not_started"
            xp_target += ls.xp_reward
            xp_earned += p.xp_earned if p else 0
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
                    is_locked=unit_locked or not _is_unlocked(user, ls),
                )
            )
        unit_completed = bool(lessons) and done == len(lessons)
        if unit_locked:
            unit_status = "locked"
        elif unit_completed:
            unit_status = "completed"
        elif done > 0 or any(lo.status == LessonProgress.Status.IN_PROGRESS for lo in lesson_outs):
            unit_status = "in_progress"
        else:
            unit_status = "not_started"
        prev_completed = unit_completed
        out_units.append(
            s.PathUnitOut(
                id=unit.id,
                order=unit.order,
                code=unit.code,
                title_vi=unit.title_vi,
                title_en=unit.title_en,
                subtitle=unit.subtitle,
                description_vi=unit.description_vi,
                status=unit_status,
                is_locked=unit_locked,
                reward=unit.reward or {},
                lesson_count=len(lessons),
                done_count=done,
                lessons=lesson_outs,
            )
        )

    total_done = sum(u.done_count for u in out_units)
    path_progress = s.PathProgressOut(
        lessons_done=total_done,
        lessons_total=lessons_total,
        xp_earned=xp_earned,
        xp_target=xp_target,
    )
    milestones = [
        s.PathMilestoneOut(
            name=ms.name,
            title_vi=ms.title_vi,
            requirement_lessons=ms.requirement_lessons,
            current_lessons=total_done,
            reward_xp=ms.reward_xp,
            reward_coins=ms.reward_coins,
            is_reached=total_done >= ms.requirement_lessons,
        )
        for ms in LevelMilestone.objects.filter(level_id=level.upper()).order_by("order")
    ]
    return s.PathOut(
        level=level.upper(),
        level_name=level_obj.name_vi if level_obj else "",
        tier_label=level_obj.tier_label if level_obj else "",
        progress=path_progress,
        units=out_units,
        milestones=milestones,
    )


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


# =============================================================== vocab status + notebook
def _notebook_out(entry: NotebookEntry, accent: str, srs: dict) -> s.NotebookEntryOut:
    v = entry.vocabulary
    if v is not None:
        return s.NotebookEntryOut(
            id=entry.id,
            vocab_id=v.id,
            headword=v.headword,
            ipa=v.ipa_us if accent == "US" else v.ipa_uk,
            meaning_vi=v.meaning_vi,
            audio_url=_media(v.audio_us_path if accent == "US" else v.audio_uk_path),
            note=entry.note,
            tags=entry.tags or [],
            srs_state=srs.get(v.id),
            created_at=entry.created_at,
        )
    return s.NotebookEntryOut(
        id=entry.id,
        vocab_id=None,
        headword=entry.custom_word,
        ipa="",
        meaning_vi=entry.custom_meaning,
        audio_url=None,
        note=entry.note,
        tags=entry.tags or [],
        srs_state=None,
        created_at=entry.created_at,
    )


@router.get(
    "/learn/vocabulary/status",
    response={200: s.VocabStatusOut, 401: ErrorOut},
    summary="Trạng thái từ vựng của một cấp (động cơ tab Từ vựng)",
    description="Tổng hợp + 7 ô tuần + tiến độ chủ đề + sổ tay + 3 mảng id để lọc tab cục bộ.",
)
def vocabulary_status(request, level: str):
    user = request.auth
    profile = ensure_profile(user)
    lv = level.upper()
    today = services.local_today(profile)
    end_today = datetime.combine(today, dtime.max, ZoneInfo(profile.timezone))

    total = Level.objects.filter(code=lv).values_list("word_target", flat=True).first() or 0
    cards = list(
        SRSCard.objects.filter(user=user, vocabulary__level_id=lv).values(
            "vocabulary_id", "state", "due_at"
        )
    )
    studied = len(cards)
    mastered = sum(1 for c in cards if c["state"] == SRSCard.State.REVIEW)
    learned_ids = [c["vocabulary_id"] for c in cards]
    due_ids = [
        c["vocabulary_id"]
        for c in cards
        if c["due_at"] <= end_today and c["state"] != SRSCard.State.SUSPENDED
    ]

    nb = list(NotebookEntry.objects.filter(user=user).values("vocabulary_id", "tags"))
    fav_level_ids = list(
        NotebookEntry.objects.filter(
            user=user, vocabulary__level_id=lv, vocabulary__isnull=False
        ).values_list("vocabulary_id", flat=True)
    )
    categories = len({t for n in nb for t in (n["tags"] or [])})

    topic_vocab: dict[int, set[int]] = {}
    for tid, vid in Vocabulary.objects.filter(level_id=lv, topics__isnull=False).values_list(
        "topics", "id"
    ):
        topic_vocab.setdefault(tid, set()).add(vid)
    learned_set = set(learned_ids)
    topics = [
        s.VocabTopicOut(id=t.id, done=len(vids & learned_set), total=len(vids))
        for t in Topic.objects.filter(id__in=topic_vocab.keys())
        if (vids := topic_vocab[t.id])
    ]

    week = [d.active for d in _week_progress(user, today)]

    return s.VocabStatusOut(
        level=lv,
        summary=s.VocabSummaryOut(
            total=total,
            studied=studied,
            mastered=mastered,
            learning=studied - mastered,
            due_today=len(due_ids),
            percent=min(100, round(studied / total * 100)) if total else 0,
        ),
        week=week,
        notebook=s.VocabNotebookOut(total=len(nb), categories=categories),
        topics=topics,
        learned_ids=learned_ids,
        due_ids=due_ids,
        fav_ids=fav_level_ids,
    )


@router.get(
    "/learn/notebook",
    response={200: Page[s.NotebookEntryOut], 401: ErrorOut},
    summary="Sổ tay từ vựng",
    description="Danh sách mục sổ tay (lọc theo `tag`), kèm trạng thái SRS mỗi từ.",
)
def notebook_list(
    request,
    tag: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    user = request.auth
    profile = ensure_profile(user)
    qs = NotebookEntry.objects.filter(user=user).select_related("vocabulary")
    if tag:
        qs = qs.filter(tags__contains=[tag])
    qs = qs.order_by("-created_at")
    count = qs.count()
    items = list(qs[offset : offset + limit])
    srs = dict(
        SRSCard.objects.filter(
            user=user, vocabulary_id__in=[e.vocabulary_id for e in items if e.vocabulary_id]
        ).values_list("vocabulary_id", "state")
    )
    return Page(
        items=[_notebook_out(e, profile.accent, srs) for e in items],
        count=count,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/learn/notebook",
    response={200: s.NotebookEntryOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    summary="Lưu từ vào sổ tay",
    description="Free ≤100, Premium ≤4.000 → `notebook_limit`. Trùng từ thì cập nhật ghi chú/tag.",
)
def notebook_add(request, payload: s.NotebookCreateIn):
    user = request.auth
    profile = ensure_profile(user)

    vocab = None
    if payload.vocab_id is not None:
        vocab = Vocabulary.objects.filter(id=payload.vocab_id).first()
        if vocab is None:
            raise NotFound("Không tìm thấy từ vựng")

    existing = None
    if vocab is not None:
        existing = NotebookEntry.objects.filter(user=user, vocabulary=vocab).first()

    if existing is None:
        limit = NOTEBOOK_LIMITS[profile.is_premium]
        if NotebookEntry.objects.filter(user=user).count() >= limit:
            raise Forbidden(f"Sổ tay đã đầy (tối đa {limit} từ)", code="notebook_limit")

    entry, _ = NotebookEntry.objects.update_or_create(
        user=user,
        vocabulary=vocab,
        custom_word=payload.custom_word if vocab is None else "",
        defaults={
            "custom_meaning": payload.custom_meaning if vocab is None else "",
            "note": payload.note,
            "tags": payload.tags,
        },
    )
    srs = {}
    if vocab is not None:
        state = (
            SRSCard.objects.filter(user=user, vocabulary=vocab)
            .values_list("state", flat=True)
            .first()
        )
        if state is not None:
            srs[vocab.id] = state
    return _notebook_out(entry, profile.accent, srs)


@router.delete(
    "/learn/notebook/{id}",
    response={204: None, 401: ErrorOut, 404: ErrorOut},
    summary="Xoá mục sổ tay",
    description="Chỉ xoá mục của chính người dùng.",
)
def notebook_delete(request, id: int):
    user = request.auth
    ensure_profile(user)
    deleted, _ = NotebookEntry.objects.filter(user=user, id=id).delete()
    if not deleted:
        raise NotFound("Không tìm thấy mục sổ tay")
    return HttpResponse(status=204)


# =============================================================== activity / practice / checkin / skills
_SKILL_LABELS = {
    "speaking": "Luyện nói",
    "listening": "Luyện nghe",
    "reading": "Đọc hiểu",
    "writing": "Luyện viết",
}


@router.post(
    "/learn/checkin",
    response={200: s.CheckinOut, 401: ErrorOut},
    summary="Điểm danh hàng ngày (idempotent)",
    description="Lần đầu trong ngày: +5 XP, +10 xu, giữ streak. Gọi lại trong ngày: `already=true`.",
)
def checkin(request):
    user = request.auth
    profile = ensure_profile(user)
    today = services.local_today(profile)
    tz = ZoneInfo(profile.timezone)
    start_today = datetime.combine(today, dtime.min, tz)

    already = CoinTransaction.objects.filter(
        user=user, reason="checkin", created_at__gte=start_today
    ).exists()
    if already:
        return s.CheckinOut(
            already=True,
            xp_earned=0,
            coins_earned=0,
            streak_days=profile.streak_current,
            week=_week_progress(user, today),
        )
    reward = services.record(profile, xp=5, coins=10, coin_reason="checkin")
    return s.CheckinOut(
        already=False,
        xp_earned=reward.xp_earned,
        coins_earned=reward.coins_earned,
        streak_days=reward.streak_days,
        week=_week_progress(user, today),
    )


@router.get(
    "/learn/activity",
    response={200: list[s.DailyActivityOut], 401: ErrorOut},
    summary="Lịch hoạt động (streak calendar)",
    description="Mặc định 30 ngày gần nhất; lọc `from`/`to` (YYYY-MM-DD).",
)
def activity(
    request,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
):
    user = request.auth
    profile = ensure_profile(user)
    today = services.local_today(profile)
    lo = from_date or today - timedelta(days=29)
    hi = to_date or today
    rows = DailyActivity.objects.filter(user=user, date__gte=lo, date__lte=hi).order_by("date")
    return [
        s.DailyActivityOut(
            date=r.date,
            xp=r.xp,
            lessons_completed=r.lessons_completed,
            words_reviewed=r.words_reviewed,
            speaking_count=r.speaking_count,
            minutes=r.minutes,
        )
        for r in rows
    ]


@router.post(
    "/learn/practice",
    response={200: s.PracticeResultOut, 401: ErrorOut, 422: ErrorOut},
    summary="Nộp kết quả luyện kỹ năng",
    description="Server chỉ nhận KẾT QUẢ (chấm phát âm ở máy). Cộng XP theo điểm + nâng UserSkill.",
)
def practice(request, payload: s.PracticeIn):
    user = request.auth
    profile = ensure_profile(user)
    xp = max(1, min(15, round(payload.score / 10)))
    with transaction.atomic():
        services.record(
            profile,
            xp=xp,
            speaking=1 if payload.kind in ("speaking", "shadowing") else 0,
            minutes=round(payload.duration_sec / 60),
        )
        skill = services.bump_skill(user, payload.kind, xp)
    return s.PracticeResultOut(
        xp_earned=xp,
        skill=skill.kind if skill else None,
        skill_level=skill.level if skill else None,
        skill_percent=services.skill_percent(skill.xp) if skill else None,
    )


@router.get(
    "/learn/skills",
    response={200: s.SkillsOverviewOut, 401: ErrorOut},
    summary="Tiến độ 4 kỹ năng (Practice Hub)",
    description="Tiến độ nói/nghe/đọc/viết + gợi ý luyện kỹ năng yếu nhất hôm nay.",
)
def skills(request):
    user = request.auth
    ensure_profile(user)
    existing = {sk.kind: sk for sk in UserSkill.objects.filter(user=user)}
    out = []
    for kind in ["speaking", "listening", "reading", "writing"]:
        sk = existing.get(kind)
        xp = sk.xp if sk else 0
        out.append(
            s.SkillProgressOut(
                kind=kind, percent=services.skill_percent(xp), level=sk.level if sk else 1
            )
        )
    weakest = min(out, key=lambda x: (x.level, x.percent))
    suggestion = s.PracticeSuggestionOut(
        kind=weakest.kind, title=_SKILL_LABELS[weakest.kind], est_minutes=4, xp=10
    )
    return s.SkillsOverviewOut(skills=out, suggestion=suggestion)


@router.get(
    "/learn/practice-hub",
    response={200: s.PracticeHubOut, 401: ErrorOut},
    summary="Trung tâm luyện tập (C19) — gộp 1 lần gọi",
    description="Hồ sơ tóm tắt, hội thoại AI nổi bật, tiến độ kỹ năng, số liệu (từ ôn/sổ tay) "
    "và danh sách trò chơi cho tab Luyện tập.",
)
def practice_hub(request):
    user = request.auth
    profile = ensure_profile(user)

    existing = {sk.kind: sk for sk in UserSkill.objects.filter(user=user)}
    skills_out = [
        s.SkillProgressOut(
            kind=kind,
            percent=services.skill_percent(existing[kind].xp if kind in existing else 0),
            level=existing[kind].level if kind in existing else 1,
        )
        for kind in ["speaking", "listening", "reading", "writing"]
    ]

    scenario = RoleplayScenario.objects.order_by("-is_premium", "id").first()
    featured = (
        s.PracticeFeaturedOut(
            title_vi=scenario.title_vi,
            topic=scenario.topic,
            description_vi=scenario.description_vi,
            is_premium=scenario.is_premium,
            thumbnail_url=_media(scenario.thumbnail_path),
        )
        if scenario
        else None
    )

    dialogues = Dialogue.objects.count()
    videos = Video.objects.count()
    readings = Reading.objects.count()
    counts = s.PracticeCountsOut(
        vocab_due=SRSCard.objects.filter(user=user, due_at__lte=djtz.now()).exclude(state=4).count(),
        notebook_total=NotebookEntry.objects.filter(user=user).count(),
        ipa_sounds=IPASound.objects.count(),
        videos=videos,
        skills=s.PracticeSkillCountsOut(
            speaking=ShadowingDeck.objects.count() + dialogues,
            listening=dialogues + videos,
            reading=readings + Story.objects.count(),
            writing=GrammarPoint.objects.count(),
        ),
    )

    games = [
        s.PracticeGameOut(
            id=g.id,
            code=g.code,
            title_vi=g.title_vi,
            description_vi=g.description_vi,
            kind=g.kind,
            icon_url=_media(g.icon_path),
            is_featured=g.is_featured,
        )
        for g in Game.objects.filter(is_active=True).order_by("order", "id")
    ]

    return s.PracticeHubOut(
        streak_days=profile.streak_current,
        coins=profile.coins,
        hearts=profile.hearts,
        is_premium=profile.is_premium,
        featured=featured,
        skills=skills_out,
        counts=counts,
        games=games,
    )


# =============================================================== me preferences + avatar
def _preferences_out(user, profile) -> s.PreferencesOut:
    return s.PreferencesOut(
        full_name=user.full_name,
        goal_level=profile.goal_level,
        cefr_level=profile.cefr_level,
        learning_goal=profile.learning_goal,
        accent=profile.accent,
        show_ipa=profile.show_ipa,
        daily_goal_xp=profile.daily_goal_xp,
        daily_goal_words=profile.daily_goal_words,
        timezone=profile.timezone,
        ui_language=profile.ui_language,
        reminder_enabled=profile.reminder_enabled,
        reminder_time=profile.reminder_time.strftime("%H:%M"),
        streak_reminder=profile.streak_reminder,
        event_notifications=profile.event_notifications,
        is_premium=profile.is_premium,
        onboarding_completed=profile.onboarding_completed,
        onboarding_completed_at=profile.onboarding_completed_at,
    )


@router.patch(
    "/me/preferences",
    response={200: s.PreferencesOut, 401: ErrorOut, 422: ErrorOut},
    summary="Cập nhật tuỳ chọn (partial)",
    description=(
        "Chỉ gửi trường cần đổi. `reminder_time` dạng 'HH:MM'. "
        "Gửi `onboarding_completed=true` sau khi người dùng hoàn tất chọn trình độ."
    ),
)
def update_preferences(request, payload: s.MePreferencesIn):
    user = request.auth
    profile = ensure_profile(user)
    data = payload.dict(exclude_unset=True)

    if "full_name" in data:
        user.full_name = data.pop("full_name")
        user.save(update_fields=["full_name"])

    if "reminder_time" in data:
        try:
            hh, mm = data["reminder_time"].split(":")
            data["reminder_time"] = dtime(int(hh), int(mm))
        except (ValueError, AttributeError) as e:
            raise AppError(
                "Giờ nhắc không hợp lệ (HH:MM)",
                code="validation_error",
                status_code=422,
                details={"reminder_time": ["Định dạng HH:MM"]},
            ) from e

    if "onboarding_completed" in data:
        data["onboarding_completed_at"] = djtz.now() if data["onboarding_completed"] else None

    for field, value in data.items():
        setattr(profile, field, value)
    if data:
        profile.save()
    return _preferences_out(user, profile)


@router.post(
    "/me/avatar",
    response={200: s.AvatarOut, 401: ErrorOut, 413: ErrorOut, 415: ErrorOut},
    summary="Tải ảnh đại diện",
    description="Ảnh JPEG/PNG/WebP ≤ 5MB → upload R2, ghi đường dẫn hồ sơ.",
)
def avatar(request, file: UploadedFile = File(...)):
    user = request.auth
    ensure_profile(user)
    ext = _AVATAR_TYPES.get(file.content_type)
    if ext is None:
        raise AppError(
            "Chỉ nhận ảnh JPEG/PNG/WebP", code="unsupported_media_type", status_code=415
        )
    data = file.read()
    if len(data) > _AVATAR_MAX:
        raise AppError("Ảnh quá lớn (tối đa 5MB)", code="payload_too_large", status_code=413)
    key = f"avatars/{user.id}.{ext}"
    upload_avatar(key, data, file.content_type)
    user.avatar_path = key
    user.save(update_fields=["avatar_path"])
    return s.AvatarOut(avatar_url=_media(key))


# =============================================================== placement (C23)
_PLACEMENT_LABELS = {"vocab": "Từ vựng", "grammar": "Ngữ pháp", "listening": "Nghe"}


@router.get(
    "/placement/questions",
    response={200: list[s.PlacementQuestionOut], 401: ErrorOut},
    summary="Câu hỏi xếp lớp đầu vào",
    description="~12 câu, KHÔNG lộ đáp án. Chấm ở server sau khi nộp.",
)
def placement_questions(request):
    ensure_profile(request.auth)
    qs = PlacementQuestion.objects.filter(is_active=True).order_by("order")[:12]
    return [
        s.PlacementQuestionOut(
            id=q.id,
            order=q.order,
            skill=q.skill,
            prompt_en=q.prompt_en,
            options=q.options,
            audio_url=_media(q.audio_path),
        )
        for q in qs
    ]


@router.post(
    "/placement/submit",
    response={200: s.PlacementResultOut, 401: ErrorOut, 422: ErrorOut},
    summary="Nộp bài xếp lớp",
    description="Chấm server → cấp đề xuất + unit bắt đầu + điểm theo kỹ năng + số ngày tiết kiệm.",
)
def placement_submit(request, payload: list[s.PlacementAnswerIn]):
    user = request.auth
    profile = ensure_profile(user)
    answers = {a.question_id: a.answer for a in payload}
    questions = {q.id: q for q in PlacementQuestion.objects.filter(id__in=answers.keys())}

    by_skill: dict[str, list[int]] = {}
    by_level: dict[str, list[int]] = {}
    for qid, ans in answers.items():
        q = questions.get(qid)
        if q is None:
            continue
        ok = int(ans == q.answer_index)
        by_skill.setdefault(q.skill, [0, 0])
        by_skill[q.skill][0] += ok
        by_skill[q.skill][1] += 1
        by_level.setdefault(q.level, [0, 0])
        by_level[q.level][0] += ok
        by_level[q.level][1] += 1

    suggested = "A1"
    for lv in _CEFR_ORDER:
        c, t = by_level.get(lv, [0, 0])
        if t > 0 and c / t >= 0.6:
            suggested = lv

    lv_order = _CEFR_ORDER.index(suggested)
    start_unit = Unit.objects.filter(level_id=suggested).order_by("order").first()
    skipped = Unit.objects.filter(level__order__lt=lv_order + 1).count()

    PlacementAttempt.objects.create(
        user=user,
        answers={str(k): v for k, v in answers.items()},
        score_by_skill={k: v[0] for k, v in by_skill.items()},
        suggested_level=suggested,
        suggested_unit=start_unit,
    )
    profile.cefr_level = suggested
    profile.save(update_fields=["cefr_level"])

    return s.PlacementResultOut(
        suggested_level=suggested,
        start_unit_code=start_unit.code if start_unit else None,
        skill_scores=[
            s.PlacementSkillScoreOut(
                skill=k, correct=v[0], total=v[1], label=_PLACEMENT_LABELS.get(k, k)
            )
            for k, v in by_skill.items()
        ],
        days_saved=skipped * 2,
    )
