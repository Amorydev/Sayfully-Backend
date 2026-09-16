"""21 endpoint nội dung học (G2). Tất cả `Bearer`.

Chỉ trả NỘI DUNG; tiến độ người dùng thuộc G4. Cấp có `is_free=False` cần Premium (🔒).
`audio_url` ghép đầy đủ từ `R2_PUBLIC_BASE`; `ipa` theo `UserProfile.accent`.
"""

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from ninja import Query, Router

from apps.accounts.services import ensure_profile
from apps.common.exceptions import Forbidden, NotFound
from apps.common.schemas import ErrorOut
from apps.learning import services as learn_services
from apps.learning.models import GrammarProgress, IPASoundProgress, WordRootProgress

from . import models as m
from . import schemas as s
from . import video_import

router = Router()

_PREMIUM = "Nội dung này dành cho Premium"
_NOTFOUND = "Không tìm thấy nội dung"


# --------------------------------------------------------------- helpers
def _media(path: str | None) -> str | None:
    if not path:
        return None
    return f"{settings.R2_PUBLIC_BASE.rstrip('/')}/{path}"


def _ipa(vocab: m.Vocabulary, accent: str) -> str:
    return vocab.ipa_us if accent == "US" else vocab.ipa_uk


def _syllables(vocab: m.Vocabulary) -> list[s.SyllableOut]:
    return [
        s.SyllableOut(
            text=syl,
            is_primary=(i == vocab.primary_stress),
            is_secondary=(i == vocab.secondary_stress),
        )
        for i, syl in enumerate(vocab.ipa_syllables or [])
    ]


def _gate(profile, level: m.Level) -> None:
    if not level.is_free and not profile.is_premium:
        raise Forbidden(_PREMIUM, code="premium_required")


def _sentence(text_en: str, ipa: str, text_vi: str, audio_path: str) -> s.SentenceOut:
    return s.SentenceOut(
        text_en=text_en, ipa=ipa or None, text_vi=text_vi, audio_url=_media(audio_path)
    )


def _example(e: m.VocabularyExample) -> s.ExampleOut:
    return s.ExampleOut(text_en=e.text_en, text_vi=e.text_vi, audio_url=_media(e.audio_path))


# --------------------------------------------------------------- builders: vocab
def _vocab_list(
    v: m.Vocabulary,
    accent: str,
    notebook_entry_id: int | None = None,
) -> s.VocabListOut:
    audio = v.audio_us_path if accent == "US" else v.audio_uk_path
    return s.VocabListOut(
        id=v.id,
        headword=v.headword,
        pos=v.pos,
        level=v.level_id,
        meaning_vi=v.meaning_vi,
        ipa=_ipa(v, accent),
        syllables=_syllables(v),
        audio_url=_media(audio),
        is_saved=notebook_entry_id is not None,
        notebook_entry_id=notebook_entry_id,
    )


def _vocab_card(v: m.Vocabulary, accent: str) -> s.VocabCardOut:
    return s.VocabCardOut(
        id=v.id,
        headword=v.headword,
        pos=v.pos,
        level=v.level_id,
        ipa=_ipa(v, accent),
        syllables=_syllables(v),
        meaning_vi=v.meaning_vi,
        audio_uk_url=_media(v.audio_uk_path),
        audio_us_url=_media(v.audio_us_path),
        examples=[_example(e) for e in v.examples.all()],
    )


def _related_word(v: m.Vocabulary) -> s.RelatedWordOut:
    return s.RelatedWordOut(
        id=v.id,
        headword=v.headword,
        pos=v.pos,
        meaning_vi=v.meaning_vi,
    )


def _named_related_word(name: str, by_headword: dict[str, m.Vocabulary]) -> s.RelatedWordOut:
    vocabulary = by_headword.get(name.casefold())
    return _related_word(vocabulary) if vocabulary else s.RelatedWordOut(headword=name)


def _vocab_detail(
    v: m.Vocabulary,
    accent: str,
    notebook_entry_id: int | None = None,
    named_related: dict[str, m.Vocabulary] | None = None,
) -> s.VocabDetailOut:
    related = named_related or {}
    return s.VocabDetailOut(
        id=v.id,
        headword=v.headword,
        pos=v.pos,
        level=v.level_id,
        ipa=_ipa(v, accent),
        ipa_uk=v.ipa_uk,
        ipa_us=v.ipa_us,
        syllables=_syllables(v),
        meaning_vi=v.meaning_vi,
        definition_en=v.definition_en,
        definition_vi=v.definition_vi,
        audio_uk_url=_media(v.audio_uk_path),
        audio_us_url=_media(v.audio_us_path),
        frequency_rank=v.frequency_rank,
        synonyms=v.synonyms or [],
        antonyms=v.antonyms or [],
        word_family=[w.headword for w in v.word_family.all()],
        synonym_items=[_named_related_word(name, related) for name in (v.synonyms or [])],
        antonym_items=[_named_related_word(name, related) for name in (v.antonyms or [])],
        word_family_items=[_related_word(word) for word in v.word_family.all()],
        is_saved=notebook_entry_id is not None,
        notebook_entry_id=notebook_entry_id,
        examples=[_example(e) for e in v.examples.all()],
        collocations=[
            s.CollocationOut(text_en=c.text_en, meaning_vi=c.meaning_vi)
            for c in v.collocations.all()
        ],
    )


# --------------------------------------------------------------- builders: grammar
def _conjugation(gp: m.GrammarPoint) -> list[s.ConjugationRowOut]:
    return [
        s.ConjugationRowOut(subject=r.get("subject", ""), form=r.get("form", ""))
        for r in (gp.conjugation or [])
    ]


def _grammar_examples(gp: m.GrammarPoint) -> list[s.SentenceOut]:
    return [_sentence(e.text_en, e.ipa, e.text_vi, e.audio_path) for e in gp.examples.all()]


# --------------------------------------------------------------- builders: lesson steps
def _lesson_step(step: m.LessonStep, accent: str) -> s.LessonStepOut:
    out = s.LessonStepOut(order=step.order, kind=step.kind)
    if step.kind == m.LessonStep.Kind.INTRO:
        p = step.payload or {}
        out.intro = s.IntroStepOut(
            highlight_vi=p.get("highlight_vi", ""),
            preview=[
                _sentence(
                    x.get("text_en", ""),
                    x.get("ipa", ""),
                    x.get("text_vi", ""),
                    x.get("audio_path", ""),
                )
                for x in p.get("preview", [])
            ],
        )
    elif step.kind == m.LessonStep.Kind.VOCAB and step.vocabulary_id:
        out.vocab = _vocab_card(step.vocabulary, accent)
    elif step.kind == m.LessonStep.Kind.GRAMMAR and step.grammar_point_id:
        gp = step.grammar_point
        out.grammar = s.GrammarStepOut(
            id=gp.id,
            title_vi=gp.title_vi,
            title_en=gp.title_en,
            formula=gp.formula,
            note_vi=gp.note_vi,
            explanation_vi=gp.explanation_vi,
            common_mistake_vi=gp.common_mistake_vi,
            conjugation=_conjugation(gp),
            examples=_grammar_examples(gp),
        )
    elif step.kind == m.LessonStep.Kind.DIALOGUE and step.dialogue_id:
        d = step.dialogue
        out.dialogue = s.DialogueStepOut(
            id=d.id,
            title_en=d.title_en,
            title_vi=d.title_vi,
            context_vi=d.context_vi,
            lines=[
                s.DialogueLineOut(
                    order=ln.order,
                    speaker=ln.speaker,
                    is_native=ln.is_native,
                    text_en=ln.text_en,
                    ipa=ln.ipa or None,
                    text_vi=ln.text_vi,
                    audio_url=_media(ln.audio_path),
                )
                for ln in d.lines.all()
            ],
        )
    elif step.kind == m.LessonStep.Kind.SPELLING:
        p = step.payload or {}
        v = step.vocabulary
        audio_path = (
            (v.audio_us_path if accent == "US" else v.audio_uk_path)
            if v
            else p.get("audio_path", "")
        )
        out.spelling = s.SpellingStepOut(
            vocab_id=step.vocabulary_id,
            word=v.headword if v else p.get("word", ""),
            meaning_vi=v.meaning_vi if v else p.get("meaning_vi", ""),
            ipa=_ipa(v, accent) if v else p.get("ipa"),
            audio_url=_media(audio_path),
            hint_vi=p.get("hint_vi", ""),
        )
    elif step.kind == m.LessonStep.Kind.WRITING:
        p = step.payload or {}
        out.writing = s.WritingStepOut(
            prompt_vi=p.get("prompt_vi", ""),
            hint_vi=p.get("hint_vi", ""),
            suggestions=p.get("suggestions", []),
            xp=p.get("xp", 20),
        )
    elif step.kind == m.LessonStep.Kind.QUIZ:
        p = step.payload or {}
        v = step.vocabulary
        out.quiz = s.QuizStepOut(
            prompt_vi=p.get("prompt_vi", ""),
            question_word=v.headword if v else p.get("question_word", ""),
            question_ipa=_ipa(v, accent) if v else p.get("question_ipa"),
            audio_url=_media(p.get("audio_path", "")),
            options=[s.QuizOptionOut(text=o) for o in p.get("options", [])],
            correct_index=p.get("correct_index", 0),
            explanation_vi=p.get("explanation_vi", ""),
            xp=p.get("xp", 10),
        )
    return out


# =============================================================== 2.1 Lộ trình
@router.get(
    "/levels",
    response={200: list[s.LevelOut], 401: ErrorOut},
    summary="Danh sách cấp CEFR",
    description="6 cấp A1→C2 kèm mục tiêu số từ và cờ miễn phí (`is_free`).",
)
def list_levels(request):
    return [
        s.LevelOut(
            code=lv.code,
            name_vi=lv.name_vi,
            tier_label=lv.tier_label,
            description_vi=lv.description_vi,
            order=lv.order,
            word_target=lv.word_target,
            is_free=lv.is_free,
        )
        for lv in m.Level.objects.order_by("order")
    ]


@router.get(
    "/levels/{code}/units",
    response={200: list[s.UnitOut], 401: ErrorOut, 404: ErrorOut},
    summary="Danh sách unit của một cấp",
    description="Các unit theo thứ tự, kèm số bài (`lesson_count`) và rương thưởng.",
)
def list_units(request, code: str):
    level = m.Level.objects.filter(code=code.upper()).first()
    if level is None:
        raise NotFound(_NOTFOUND)
    units = (
        m.Unit.objects.filter(level=level).annotate(n_lessons=Count("lessons")).order_by("order")
    )
    return [
        s.UnitOut(
            id=u.id,
            order=u.order,
            code=u.code,
            title_vi=u.title_vi,
            title_en=u.title_en,
            description_vi=u.description_vi,
            lesson_count=u.n_lessons,
            reward=u.reward or {},
        )
        for u in units
    ]


@router.get(
    "/units/{id}",
    response={200: s.UnitDetailOut, 401: ErrorOut, 404: ErrorOut},
    summary="Chi tiết unit kèm danh sách bài",
    description="Nội dung unit + danh sách bài (không kèm tiến độ — tiến độ ở G4).",
)
def get_unit(request, id: int):
    unit = m.Unit.objects.filter(id=id).first()
    if unit is None:
        raise NotFound(_NOTFOUND)
    lessons = unit.lessons.order_by("order")
    return s.UnitDetailOut(
        id=unit.id,
        order=unit.order,
        code=unit.code,
        title_vi=unit.title_vi,
        title_en=unit.title_en,
        description_vi=unit.description_vi,
        reward=unit.reward or {},
        lessons=[
            s.LessonBriefOut(
                id=ls.id,
                code=ls.code,
                order=ls.order,
                title_vi=ls.title_vi,
                title_en=ls.title_en,
                est_minutes=ls.est_minutes,
                xp_reward=ls.xp_reward,
            )
            for ls in lessons
        ],
    )


@router.get(
    "/lessons/{code}",
    response={200: s.LessonDetailOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Chi tiết bài học (lồng đủ các bước)",
    description=(
        "Trả toàn bộ bước học đa hình theo `kind` trong **một lần gọi**.\n\n"
        "Chi tiết cấp có `is_free=False` cần Premium (`premium_required`). Bước `writing` chỉ có "
        "khi bật AI."
    ),
)
def get_lesson(request, code: str):
    profile = ensure_profile(request.auth)
    lesson = m.Lesson.objects.filter(code=code).select_related("unit", "unit__level").first()
    if lesson is None:
        raise NotFound(_NOTFOUND)
    _gate(profile, lesson.unit.level)

    steps = lesson.steps.select_related("vocabulary", "grammar_point", "dialogue").order_by("order")
    step_outs, n_vocab, n_grammar, n_dialogue = [], 0, 0, 0
    for step in steps:
        if step.kind == m.LessonStep.Kind.VOCAB:
            n_vocab += 1
        elif step.kind == m.LessonStep.Kind.GRAMMAR:
            n_grammar += 1
        elif step.kind == m.LessonStep.Kind.DIALOGUE:
            n_dialogue += 1
        step_outs.append(_lesson_step(step, profile.accent))

    return s.LessonDetailOut(
        code=lesson.code,
        order=lesson.order,
        unit=s.UnitRefOut(
            id=lesson.unit_id,
            order=lesson.unit.order,
            title_vi=lesson.unit.title_vi,
            title_en=lesson.unit.title_en,
        ),
        level=lesson.unit.level_id,
        title_vi=lesson.title_vi,
        title_en=lesson.title_en,
        description_vi=lesson.description_vi,
        est_minutes=lesson.est_minutes,
        xp_reward=lesson.xp_reward,
        new_word_count=n_vocab,
        grammar_count=n_grammar,
        dialogue_count=n_dialogue,
        steps=step_outs,
    )


# =============================================================== 2.2 Từ vựng
@router.get(
    "/vocabulary",
    response={200: s.Page[s.VocabListOut], 401: ErrorOut, 422: ErrorOut},
    summary="Danh sách / tìm từ vựng",
    description="Lọc theo `level`, `topic`, `pos`; `q` tìm đồng thời từ + IPA + nghĩa.",
)
def list_vocabulary(
    request,
    level: str | None = None,
    topic: str | None = None,
    q: str | None = None,
    pos: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    profile = ensure_profile(request.auth)
    qs = m.Vocabulary.objects.all()
    if level:
        qs = qs.filter(level_id=level.upper())
    if pos:
        qs = qs.filter(pos=pos)
    if topic:
        qs = qs.filter(topics__code=topic)
    if q:
        qs = qs.filter(
            Q(headword__icontains=q)
            | Q(meaning_vi__icontains=q)
            | Q(ipa_us__icontains=q)
            | Q(ipa_uk__icontains=q)
        )
    qs = qs.distinct().order_by("frequency_rank", "headword")
    count = qs.count()
    items = list(qs[offset : offset + limit])
    # Import cục bộ để content không tạo vòng import module với learning.
    from apps.learning.models import NotebookEntry

    notebook_entries = dict(
        NotebookEntry.objects.filter(
            user=request.auth,
            vocabulary_id__in=[item.id for item in items],
        ).values_list("vocabulary_id", "id")
    )
    return s.Page(
        items=[_vocab_list(v, profile.accent, notebook_entries.get(v.id)) for v in items],
        count=count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/vocabulary/{id}",
    response={200: s.VocabDetailOut, 401: ErrorOut, 404: ErrorOut},
    summary="Chi tiết một từ vựng",
    description="Đầy đủ ví dụ, collocation, gia đình từ, đồng nghĩa, phân tích âm tiết.",
)
def get_vocabulary(request, id: int):
    profile = ensure_profile(request.auth)
    v = (
        m.Vocabulary.objects.filter(id=id)
        .prefetch_related("examples", "collocations", "word_family")
        .first()
    )
    if v is None:
        raise NotFound(_NOTFOUND)
    from apps.learning.models import NotebookEntry

    notebook_entry_id = (
        NotebookEntry.objects.filter(
            user=request.auth,
            vocabulary=v,
        )
        .values_list("id", flat=True)
        .first()
    )
    named_words = set(v.synonyms or []) | set(v.antonyms or [])
    related = {
        word.headword.casefold(): word
        for word in m.Vocabulary.objects.filter(headword__in=named_words).order_by(
            "frequency_rank", "id"
        )
    }
    return _vocab_detail(v, profile.accent, notebook_entry_id, related)


@router.get(
    "/topics",
    response={200: list[s.TopicOut], 401: ErrorOut},
    summary="Danh sách chủ đề từ vựng",
    description="Chủ đề kèm số từ (`word_count`) để hiển thị 'Chủ đề nổi bật'.",
)
def list_topics(request):
    topics = m.Topic.objects.annotate(n=Count("vocabulary")).order_by("order")
    return [
        s.TopicOut(
            id=t.id,
            code=t.code,
            name_vi=t.name_vi,
            name_en=t.name_en,
            icon=t.icon,
            word_count=t.n,
        )
        for t in topics
    ]


# =============================================================== 2.3 Ngữ pháp
def _grammar_completed_ids(user) -> set[int]:
    return set(
        GrammarProgress.objects.filter(user=user, completed_at__isnull=False).values_list(
            "grammar_point_id", flat=True
        )
    )


@router.get(
    "/grammar",
    response={200: s.GrammarPageOut, 401: ErrorOut, 422: ErrorOut},
    summary="Danh sách điểm ngữ pháp",
    description=(
        "Lọc theo `level` (mặc định cấp của người dùng), `category`; `q` tìm theo tiêu đề. Kèm chip "
        "danh mục của cấp, số điểm đã hoàn thành và mẹo vàng."
    ),
)
def list_grammar(
    request,
    level: str | None = None,
    category: str | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    profile = ensure_profile(request.auth)
    level_code = (level or profile.cefr_level or "A1").upper()
    base = m.GrammarPoint.objects.filter(level_id=level_code).select_related("level")
    categories = [
        c for c in base.order_by("order").values_list("category", flat=True).distinct() if c
    ]
    qs = base
    if category:
        qs = qs.filter(category=category)
    if q:
        qs = qs.filter(Q(title_vi__icontains=q) | Q(title_en__icontains=q))
    qs = qs.annotate(n_ex=Count("exercises")).order_by("order")
    count = qs.count()
    items = list(qs[offset : offset + limit])
    done = _grammar_completed_ids(request.auth)
    tip = next((g.note_vi for g in base.order_by("order") if g.id not in done and g.note_vi), "")
    return s.GrammarPageOut(
        items=[
            s.GrammarListOut(
                id=g.id,
                level=g.level_id,
                order=g.order,
                category=g.category,
                title_vi=g.title_vi,
                title_en=g.title_en,
                subtitle_vi=g.subtitle_vi,
                formula=g.formula,
                exercise_count=g.n_ex,
                completed=g.id in done,
                is_locked=not g.level.is_free and not profile.is_premium,
            )
            for g in items
        ],
        count=count,
        limit=limit,
        offset=offset,
        categories=list(dict.fromkeys(categories)),
        completed=sum(1 for gid in base.values_list("id", flat=True) if gid in done),
        tip_vi=tip,
    )


@router.get(
    "/grammar/{id}",
    response={200: s.GrammarDetailOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Chi tiết điểm ngữ pháp",
    description="Công thức (kèm từng thành phần), bảng chia, ví dụ, lỗi hay gặp, tiến độ. Cấp có `is_free=False` cần Premium.",
)
def get_grammar(request, id: int):
    profile = ensure_profile(request.auth)
    g = (
        m.GrammarPoint.objects.filter(id=id)
        .select_related("level")
        .prefetch_related("examples")
        .first()
    )
    if g is None:
        raise NotFound(_NOTFOUND)
    _gate(profile, g.level)
    siblings = list(
        m.GrammarPoint.objects.filter(level=g.level).order_by("order").values_list("id", flat=True)
    )
    prog = GrammarProgress.objects.filter(user=request.auth, grammar_point=g).first()
    return s.GrammarDetailOut(
        id=g.id,
        level=g.level_id,
        order=g.order,
        position=siblings.index(g.id) + 1 if g.id in siblings else 1,
        total_in_level=len(siblings),
        category=g.category,
        title_vi=g.title_vi,
        title_en=g.title_en,
        subtitle_vi=g.subtitle_vi,
        form_vi=g.form_vi,
        formula=g.formula,
        formula_parts=[
            s.FormulaPartOut(token=p.get("token", ""), label_vi=p.get("label_vi", ""))
            for p in (g.formula_parts or [])
        ],
        note_vi=g.note_vi,
        explanation_vi=g.explanation_vi,
        common_mistake_vi=g.common_mistake_vi,
        mistake_wrong=g.mistake_wrong,
        mistake_right=g.mistake_right,
        conjugation=_conjugation(g),
        examples=_grammar_examples(g),
        exercise_count=g.exercises.count(),
        xp_reward=GrammarProgress.XP_REWARD,
        completed=bool(prog and prog.completed_at),
        best_percent=prog.best_percent if prog else 0,
        attempts=prog.attempts if prog else 0,
    )


@router.get(
    "/grammar/{id}/exercises",
    response={200: list[s.GrammarExerciseOut], 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Câu thực hành của điểm ngữ pháp",
    description="Trắc nghiệm điền chỗ trống (`___` trong prompt_en). App chấm tại chỗ rồi gửi kết quả qua /practice.",
)
def list_grammar_exercises(request, id: int):
    profile = ensure_profile(request.auth)
    g = m.GrammarPoint.objects.filter(id=id).select_related("level").first()
    if g is None:
        raise NotFound(_NOTFOUND)
    _gate(profile, g.level)
    return [
        s.GrammarExerciseOut(
            id=e.id,
            order=e.order,
            prompt_en=e.prompt_en,
            prompt_vi=e.prompt_vi,
            options=e.options or [],
            answer_index=e.answer_index,
            explanation_vi=e.explanation_vi,
        )
        for e in g.exercises.all()
    ]


@router.post(
    "/grammar/{id}/practice",
    response={200: s.GrammarPracticeOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Ghi kết quả thực hành ngữ pháp",
    description="≥ 70% lần đầu → hoàn thành điểm ngữ pháp, +30 XP và tính hoạt động trong ngày (giữ streak).",
)
def practice_grammar(request, id: int, data: s.GrammarPracticeIn):
    profile = ensure_profile(request.auth)
    g = m.GrammarPoint.objects.filter(id=id).select_related("level").first()
    if g is None:
        raise NotFound(_NOTFOUND)
    _gate(profile, g.level)
    percent = min(100, round(100 * min(data.correct, data.total) / data.total))
    prog, _ = GrammarProgress.objects.get_or_create(user=request.auth, grammar_point=g)
    prog.attempts += 1
    prog.best_percent = max(prog.best_percent, percent)
    newly = False
    xp = 0
    if prog.best_percent >= GrammarProgress.COMPLETE_PERCENT and prog.completed_at is None:
        prog.completed_at = timezone.now()
        newly = True
        xp = GrammarProgress.XP_REWARD
    prog.save()
    reward = learn_services.record(profile, xp=xp, ref_type="grammar", ref_id=str(g.id), minutes=1)
    return s.GrammarPracticeOut(
        percent=percent,
        best_percent=prog.best_percent,
        attempts=prog.attempts,
        completed=prog.completed_at is not None,
        newly_completed=newly,
        xp_earned=reward.xp_earned,
        streak_days=reward.streak_days,
    )


# =============================================================== 2.4 Đọc & truyện
@router.get(
    "/readings",
    response={200: s.Page[s.ReadingListOut], 401: ErrorOut},
    summary="Danh sách bài đọc",
    description="Lọc theo `level`.",
)
def list_readings(
    request,
    level: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    qs = m.Reading.objects.select_related("topic")
    if level:
        qs = qs.filter(level_id=level.upper())
    qs = qs.annotate(n_q=Count("questions")).order_by("level__order", "order")
    count = qs.count()
    items = qs[offset : offset + limit]
    return s.Page(
        items=[
            s.ReadingListOut(
                id=r.id,
                level=r.level_id,
                order=r.order,
                title_en=r.title_en,
                title_vi=r.title_vi,
                topic=r.topic.name_vi if r.topic else None,
                est_minutes=r.est_minutes,
                cover_url=_media(r.cover_path),
                question_count=r.n_q,
            )
            for r in items
        ],
        count=count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/readings/{id}",
    response={200: s.ReadingDetailOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Chi tiết bài đọc",
    description="Câu song ngữ (IPA + audio), từ khoá, câu hỏi. Cấp có `is_free=False` cần Premium.",
)
def get_reading(request, id: int):
    profile = ensure_profile(request.auth)
    r = (
        m.Reading.objects.filter(id=id)
        .select_related("level")
        .prefetch_related("sentences", "questions", "keywords")
        .first()
    )
    if r is None:
        raise NotFound(_NOTFOUND)
    _gate(profile, r.level)
    return s.ReadingDetailOut(
        id=r.id,
        level=r.level_id,
        title_en=r.title_en,
        title_vi=r.title_vi,
        topic=r.topic.name_vi if r.topic else None,
        est_minutes=r.est_minutes,
        cover_url=_media(r.cover_path),
        sentences=[
            _sentence(sen.text_en, sen.ipa, sen.text_vi, sen.audio_path)
            for sen in r.sentences.all()
        ],
        keywords=[
            s.ReadingKeywordOut(
                id=k.id,
                headword=k.headword,
                level=k.level_id,
                ipa=_ipa(k, profile.accent),
                audio_url=_media(k.audio_us_path if profile.accent == "US" else k.audio_uk_path),
                pos=k.pos,
                meaning_vi=k.meaning_vi,
                synonyms=k.synonyms or [],
            )
            for k in r.keywords.all()
        ],
        questions=[
            s.ReadingQuestionOut(
                id=qn.id,
                order=qn.order,
                question_en=qn.question_en,
                options=qn.options,
                answer_index=qn.answer_index,
                explanation_vi=qn.explanation_vi,
            )
            for qn in r.questions.all()
        ],
    )


@router.get(
    "/stories",
    response={200: s.Page[s.StoryListOut], 401: ErrorOut},
    summary="Danh sách truyện song ngữ",
    description="Lọc theo `level`, `genre`.",
)
def list_stories(
    request,
    level: str | None = None,
    genre: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    qs = m.Story.objects.all()
    if level:
        qs = qs.filter(level_id=level.upper())
    if genre:
        qs = qs.filter(genre=genre)
    qs = qs.annotate(n_scene=Count("scenes")).order_by("level__order", "order")
    count = qs.count()
    items = qs[offset : offset + limit]
    return s.Page(
        items=[
            s.StoryListOut(
                id=st.id,
                level=st.level_id,
                order=st.order,
                title_en=st.title_en,
                title_vi=st.title_vi,
                genre=st.genre,
                synopsis_vi=st.synopsis_vi,
                cover_url=_media(st.cover_path),
                scene_count=st.n_scene,
            )
            for st in items
        ],
        count=count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/stories/{id}",
    response={200: s.StoryDetailOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Chi tiết truyện",
    description="Cảnh + câu (audio) + câu hỏi. Cấp có `is_free=False` cần Premium.",
)
def get_story(request, id: int):
    profile = ensure_profile(request.auth)
    st = (
        m.Story.objects.filter(id=id)
        .select_related("level")
        .prefetch_related("scenes__sentences", "questions")
        .first()
    )
    if st is None:
        raise NotFound(_NOTFOUND)
    _gate(profile, st.level)
    return s.StoryDetailOut(
        id=st.id,
        level=st.level_id,
        title_en=st.title_en,
        title_vi=st.title_vi,
        genre=st.genre,
        scenes=[
            s.StorySceneOut(
                order=sc.order,
                illustration_url=_media(sc.illustration_path),
                sentences=[
                    s.StorySentenceOut(
                        order=sen.order,
                        text_en=sen.text_en,
                        text_vi=sen.text_vi,
                        audio_url=_media(sen.audio_path),
                    )
                    for sen in sc.sentences.all()
                ],
            )
            for sc in st.scenes.all()
        ],
        questions=[
            s.StoryQuestionOut(
                id=qn.id,
                order=qn.order,
                question_en=qn.question_en,
                options=qn.options,
                answer_index=qn.answer_index,
                explanation_vi=qn.explanation_vi,
            )
            for qn in st.questions.all()
        ],
    )


# =============================================================== 2.5 Video & shadowing
@router.get(
    "/videos",
    response={200: s.Page[s.VideoListOut], 401: ErrorOut},
    summary="Danh sách video học",
    description="Lọc theo `level`, `category`, `featured=true` (hàng Nổi bật, sắp theo `featured_order`).",
)
def list_videos(
    request,
    level: str | None = None,
    category: str | None = None,
    featured: bool | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    qs = m.Video.objects.filter(source=m.Video.Source.CURATED)
    if level:
        qs = qs.filter(level_id=level.upper())
    if category:
        qs = qs.filter(category=category)
    if featured is not None:
        qs = qs.filter(is_featured=featured)
    qs = qs.order_by("-is_featured", "featured_order", "level__order", "id")
    count = qs.count()
    items = qs[offset : offset + limit]
    return s.Page(
        items=[
            s.VideoListOut(
                id=vd.id,
                youtube_id=vd.youtube_id,
                level=vd.level_id or "",
                title_vi=vd.title_vi,
                title_en=vd.title_en,
                category=vd.category,
                duration_sec=vd.duration_sec,
                thumbnail_url=_media(vd.thumbnail_path),
                is_free=vd.is_free,
                is_featured=vd.is_featured,
            )
            for vd in items
        ],
        count=count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/videos/preview",
    response={200: s.VideoPreviewOut, 401: ErrorOut, 403: ErrorOut, 422: ErrorOut},
    summary="Xem trước link YouTube trước khi thêm (Premium)",
    description="Tiêu đề, kênh, thời lượng và có phụ đề EN hay không. `reject_code` rỗng = thêm được.",
)
def preview_video_import(request, url: str = Query(..., min_length=5, max_length=300)):
    profile = ensure_profile(request.auth)
    video_import.ensure_can_import(profile)
    youtube_id = video_import.parse_youtube_id(url)
    if youtube_id is None:
        raise video_import.VideoImportError(video_import.reject_message("invalid_url"), code="invalid_url")
    info = video_import.preview(youtube_id)
    return s.VideoPreviewOut(
        youtube_id=info.youtube_id,
        title=info.title,
        channel=info.channel,
        duration_sec=info.duration_sec,
        has_english_captions=info.has_english_captions,
        thumbnail_url=_yt_thumb(info.youtube_id),
        reject_code=info.reject_code,
        reject_message=video_import.reject_message(info.reject_code) if info.reject_code else "",
    )


@router.post(
    "/videos/import",
    response={202: s.UserVideoOut, 401: ErrorOut, 403: ErrorOut, 422: ErrorOut, 429: ErrorOut},
    summary="Thêm video YouTube của bạn (Premium)",
    description=(
        "Tạo video học từ link YouTube có phụ đề EN. Trả `status=pending|processing`; client poll "
        "`GET /content/videos/mine` tới khi `ready`. Video đã có sẵn thì trả `ready` ngay, không tốn quota. "
        "Lỗi: `premium_required` 403, `invalid_url|no_captions|too_long|not_embeddable` 422, "
        "`video_quota_exceeded` 429."
    ),
)
def import_video(request, payload: s.VideoImportIn):
    profile = ensure_profile(request.auth)
    video = video_import.request_import(profile, payload.url)
    video.refresh_from_db()
    return 202, _user_video_out(video, profile)


@router.get(
    "/videos/mine",
    response={200: s.UserVideoListOut, 401: ErrorOut},
    summary="Video của tôi (Premium) + quota hôm nay",
)
def list_my_videos(request):
    profile = ensure_profile(request.auth)
    left, limit = video_import.quota(profile)
    return s.UserVideoListOut(
        items=[_user_video_out(vd, profile) for vd in video_import.library(profile)],
        quota=s.VideoQuotaOut(left=left, limit=limit),
        can_import=settings.VIDEO_IMPORT_ENABLED and profile.is_premium,
    )


@router.delete(
    "/videos/{id}",
    response={204: None, 401: ErrorOut, 404: ErrorOut},
    summary="Bỏ video khỏi 'Video của tôi'",
)
def remove_my_video(request, id: int):
    profile = ensure_profile(request.auth)
    if not video_import.remove_from_library(profile, id):
        raise NotFound(_NOTFOUND)
    return 204, None


@router.get(
    "/videos/{id}",
    response={200: s.VideoDetailOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Chi tiết video kèm phụ đề",
    description=(
        "Phụ đề song ngữ có timestamp + IPA. Cấp có `is_free=False` cần Premium. "
        "Video người dùng thêm: chỉ người đã thêm mới xem được; chưa `ready` thì `subtitles` rỗng."
    ),
)
def get_video(request, id: int):
    profile = ensure_profile(request.auth)
    vd = m.Video.objects.filter(id=id).select_related("level").prefetch_related("subtitles").first()
    if vd is None:
        raise NotFound(_NOTFOUND)
    if vd.source == m.Video.Source.USER:
        if not video_import.can_view(profile, vd):
            raise NotFound(_NOTFOUND)
    elif vd.level is not None:
        _gate(profile, vd.level)
    return s.VideoDetailOut(
        id=vd.id,
        youtube_id=vd.youtube_id,
        level=vd.level_id or "",
        title_vi=vd.title_vi,
        title_en=vd.title_en,
        category=vd.category,
        duration_sec=vd.duration_sec,
        source=vd.source,
        status=vd.status,
        error_code=vd.error_code,
        subtitles=[
            s.VideoSubtitleOut(
                order=sub.order,
                start_ms=sub.start_ms,
                end_ms=sub.end_ms,
                text_en=sub.text_en,
                ipa=sub.ipa,
                text_vi=sub.text_vi,
            )
            for sub in (vd.subtitles.all() if vd.status == m.Video.Status.READY else [])
        ],
    )


def _yt_thumb(youtube_id: str) -> str:
    return f"https://img.youtube.com/vi/{youtube_id}/hqdefault.jpg"


def _user_video_out(vd: m.Video, profile) -> s.UserVideoOut:
    return s.UserVideoOut(
        id=vd.id,
        youtube_id=vd.youtube_id,
        title=vd.title_vi or vd.title_en,
        channel=vd.channel,
        duration_sec=vd.duration_sec,
        level=vd.level_id,
        status=vd.status,
        error_code=vd.error_code,
        error_message=video_import.reject_message(vd.error_code) if vd.error_code else "",
        thumbnail_url=_yt_thumb(vd.youtube_id),
        added_label=video_import.added_label(vd, profile),
    )


@router.get(
    "/shadowing",
    response={200: s.Page[s.ShadowingDeckOut], 401: ErrorOut},
    summary="Danh sách bộ luyện shadowing",
    description="Lọc theo `level`.",
)
def list_shadowing(
    request,
    level: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    qs = m.ShadowingDeck.objects.all()
    if level:
        qs = qs.filter(level_id=level.upper())
    qs = qs.annotate(n_sen=Count("sentences")).order_by("level__order", "order")
    count = qs.count()
    items = qs[offset : offset + limit]
    return s.Page(
        items=[
            s.ShadowingDeckOut(
                id=dk.id,
                level=dk.level_id,
                order=dk.order,
                title_en=dk.title_en,
                title_vi=dk.title_vi,
                focus_vi=dk.focus_vi,
                est_seconds=dk.est_seconds,
                sentence_count=dk.n_sen,
                is_free=dk.is_free,
            )
            for dk in items
        ],
        count=count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/shadowing/{id}",
    response={200: s.ShadowingDetailOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Chi tiết bộ shadowing",
    description="Câu mục tiêu + IPA + audio bản xứ. Cấp có `is_free=False` cần Premium.",
)
def get_shadowing(request, id: int):
    profile = ensure_profile(request.auth)
    dk = (
        m.ShadowingDeck.objects.filter(id=id)
        .select_related("level")
        .prefetch_related("sentences")
        .first()
    )
    if dk is None:
        raise NotFound(_NOTFOUND)
    _gate(profile, dk.level)
    return s.ShadowingDetailOut(
        id=dk.id,
        level=dk.level_id,
        title_en=dk.title_en,
        title_vi=dk.title_vi,
        focus_vi=dk.focus_vi,
        sentences=[
            s.ShadowingSentenceOut(
                order=sen.order,
                text_en=sen.text_en,
                ipa=sen.ipa,
                text_vi=sen.text_vi,
                audio_url=_media(sen.audio_path),
                speaking_goal_vi=sen.speaking_goal_vi,
                highlights=sen.highlights or [],
            )
            for sen in dk.sentences.all()
        ],
    )


# =============================================================== 2.6 Tra cứu
def _root_split(root: m.WordRoot, word: str) -> tuple[str, str]:
    """Tách từ theo gốc: trả (phần còn lại, dạng "un·happy")."""
    affix = root.text.strip("-").lower()
    w = word.lower()
    if root.kind == "prefix" and w.startswith(affix) and len(w) > len(affix):
        return word[len(affix) :], f"{word[: len(affix)]}·{word[len(affix) :]}"
    if root.kind == "suffix" and w.endswith(affix) and len(w) > len(affix):
        return word[: -len(affix)], f"{word[: -len(affix)]}·{word[-len(affix) :]}"
    idx = w.find(affix)
    if idx > 0 and idx + len(affix) < len(w):
        return word[:idx] + word[
            idx + len(affix) :
        ], f"{word[:idx]}·{word[idx : idx + len(affix)]}·{word[idx + len(affix) :]}"
    return word, word


def _root_examples(root: m.WordRoot, accent: str) -> list[s.RootExampleOut]:
    """Từ vựng liên kết trước, rồi từ mẫu JSON (bỏ trùng); id = Vocabulary nếu tra được."""
    out: list[s.RootExampleOut] = []
    seen: set[str] = set()
    for v in root.examples.all():
        base, split = _root_split(root, v.headword)
        out.append(
            s.RootExampleOut(
                id=v.id,
                headword=v.headword,
                base=base,
                split=split,
                ipa=_ipa(v, accent),
                meaning_vi=v.meaning_vi,
            )
        )
        seen.add(v.headword.lower())
    for sample in root.samples or []:
        word = sample.get("word", "")
        if not word or word.lower() in seen:
            continue
        seen.add(word.lower())
        base, split = _root_split(root, word)
        base = sample.get("base") or base
        vocab = (
            m.Vocabulary.objects.filter(headword__iexact=word)
            .only("id", "ipa_uk", "ipa_us")
            .first()
        )
        out.append(
            s.RootExampleOut(
                id=vocab.id if vocab else None,
                headword=word,
                base=base,
                split=split,
                ipa=sample.get("ipa") or (_ipa(vocab, accent) if vocab else ""),
                meaning_vi=sample.get("meaning_vi", ""),
            )
        )
    return out


def _root_example_count(root: m.WordRoot) -> int:
    linked = {v.lower() for v in root.examples.values_list("headword", flat=True)}
    extra = {str(x.get("word", "")).lower() for x in (root.samples or []) if x.get("word")}
    return len(linked | extra)


@router.get(
    "/roots",
    response={200: s.WordRootBoardOut, 401: ErrorOut},
    summary="Bảng gốc từ (tiền tố / gốc / hậu tố) theo nhóm + tiến độ",
    description=(
        "Lọc `kind` = prefix | root | suffix (mặc định prefix). `total/learned` tính trên toàn bộ "
        'gốc từ để hiện "Đã học x/40"; `q` tìm theo ký tự gốc.'
    ),
)
def list_roots(request, kind: str | None = "prefix", q: str | None = None):
    learned_ids = set(
        WordRootProgress.objects.filter(user=request.auth, learned_at__isnull=False).values_list(
            "root_id", flat=True
        )
    )
    total = m.WordRoot.objects.count()
    qs = m.WordRoot.objects.prefetch_related("examples")
    if kind:
        qs = qs.filter(kind=kind)
    if q:
        qs = qs.filter(text__icontains=q)
    roots = list(qs.order_by("group_order", "order", "text"))
    groups: list[s.WordRootGroupOut] = []
    for r in roots:
        tile = s.WordRootOut(
            id=r.id,
            kind=r.kind,
            text=r.text,
            meaning_vi=r.meaning_vi,
            group_vi=r.group_vi,
            example_count=_root_example_count(r),
            learned=r.id in learned_ids,
        )
        if groups and groups[-1].title_vi == r.group_vi and groups[-1].kind == r.kind:
            groups[-1].roots.append(tile)
        else:
            groups.append(
                s.WordRootGroupOut(
                    kind=r.kind, title_vi=r.group_vi or "Khác", order=r.group_order, roots=[tile]
                )
            )
    return s.WordRootBoardOut(
        total=total,
        learned=len(learned_ids),
        kind_total=len(roots),
        kind_learned=sum(1 for r in roots if r.id in learned_ids),
        groups=groups,
    )


@router.get(
    "/roots/{id}",
    response={200: s.WordRootDetailOut, 401: ErrorOut, 404: ErrorOut},
    summary="Chi tiết gốc từ kèm từ ví dụ đã tách cấu trúc",
    description="Nghĩa, tác dụng, mẹo nhớ, từ mẫu dạng `un- + happy = un·happy`, đáp án nhiễu cho bài luyện, tiến độ.",
)
def get_root(request, id: int):
    r = m.WordRoot.objects.filter(id=id).prefetch_related("examples").first()
    if r is None:
        raise NotFound(_NOTFOUND)
    profile = ensure_profile(request.auth)
    examples = _root_examples(r, profile.accent)
    own = {e.meaning_vi for e in examples}
    distractors: list[str] = []
    for other in m.WordRoot.objects.exclude(id=r.id).order_by("?")[:8]:
        for x in other.samples or []:
            mv = x.get("meaning_vi", "")
            if mv and mv not in own and mv not in distractors:
                distractors.append(mv)
        if len(distractors) >= 12:
            break
    prog = WordRootProgress.objects.filter(user=request.auth, root=r).first()
    return s.WordRootDetailOut(
        id=r.id,
        kind=r.kind,
        text=r.text,
        meaning_vi=r.meaning_vi,
        group_vi=r.group_vi,
        effect_vi=r.effect_vi,
        mnemonic_vi=r.mnemonic_vi,
        examples=examples,
        distractors=distractors[:12],
        learned=bool(prog and prog.learned_at),
        best_percent=prog.best_percent if prog else 0,
        attempts=prog.attempts if prog else 0,
    )


@router.post(
    "/roots/{id}/practice",
    response={200: s.WordRootPracticeOut, 401: ErrorOut, 404: ErrorOut},
    summary="Ghi kết quả luyện một gốc từ",
    description="App chấm bài trắc nghiệm (đúng/tổng); ≥ 70% → gốc từ được tính là đã học.",
)
def practice_root(request, id: int, data: s.WordRootPracticeIn):
    r = m.WordRoot.objects.filter(id=id).first()
    if r is None:
        raise NotFound(_NOTFOUND)
    percent = min(100, round(100 * min(data.correct, data.total) / data.total))
    prog, _ = WordRootProgress.objects.get_or_create(user=request.auth, root=r)
    prog.attempts += 1
    prog.best_percent = max(prog.best_percent, percent)
    newly = False
    if prog.best_percent >= WordRootProgress.LEARNED_PERCENT and prog.learned_at is None:
        prog.learned_at = timezone.now()
        newly = True
    prog.save()
    return s.WordRootPracticeOut(
        percent=percent,
        best_percent=prog.best_percent,
        attempts=prog.attempts,
        learned=prog.learned_at is not None,
        newly_learned=newly,
        total_learned=WordRootProgress.objects.filter(
            user=request.auth, learned_at__isnull=False
        ).count(),
        total=m.WordRoot.objects.count(),
    )


@router.get(
    "/phrasal-verbs",
    response={200: s.Page[s.PhrasalVerbOut], 401: ErrorOut},
    summary="Danh sách phrasal verb",
    description="Lọc theo `verb_group`, `level`.",
)
def list_phrasal_verbs(
    request,
    verb_group: str | None = None,
    level: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    qs = m.PhrasalVerb.objects.all()
    if verb_group:
        qs = qs.filter(verb_group=verb_group)
    if level:
        qs = qs.filter(level_id=level.upper())
    qs = qs.order_by("verb_group", "text")
    count = qs.count()
    items = qs[offset : offset + limit]
    return s.Page(
        items=[
            s.PhrasalVerbOut(
                id=pv.id,
                verb_group=pv.verb_group,
                text=pv.text,
                ipa=pv.ipa,
                meaning_vi=pv.meaning_vi,
                explanation_vi=pv.explanation_vi,
                level=pv.level_id,
                examples=pv.examples or [],
            )
            for pv in items
        ],
        count=count,
        limit=limit,
        offset=offset,
    )


_IPA_GROUPS = [
    ("vowel", m.IPASound.Group.MONOPHTHONG),
    ("vowel", m.IPASound.Group.DIPHTHONG),
    ("consonant", m.IPASound.Group.VOICELESS),
    ("consonant", m.IPASound.Group.VOICED),
    ("consonant", m.IPASound.Group.NASAL_APPROX),
]


def _ipa_progress_map(user) -> dict[int, IPASoundProgress]:
    return {p.sound_id: p for p in IPASoundProgress.objects.filter(user=user)}


def _ipa_word_audio(word: str) -> tuple[str | None, str | None]:
    """Audio từ mẫu lấy từ kho từ vựng nếu có (khớp headword)."""
    v = (
        m.Vocabulary.objects.filter(headword__iexact=word)
        .only("audio_uk_path", "audio_us_path")
        .first()
    )
    if v is None:
        return None, None
    return _media(v.audio_uk_path), _media(v.audio_us_path)


def _ipa_tile(snd: m.IPASound, prog: IPASoundProgress | None) -> s.IPASoundOut:
    return s.IPASoundOut(
        id=snd.id,
        symbol=snd.symbol,
        kind=snd.kind,
        group=snd.group,
        category_vi=snd.category_vi,
        description_vi=snd.description_vi,
        sample_word=(snd.sample_words or [""])[0],
        sample_meaning_vi=((snd.examples or [{}])[0]).get("meaning_vi", ""),
        mastered=bool(prog and prog.mastered_at),
        best_score=prog.best_score if prog else 0,
        audio_uk_url=_media(snd.audio_uk_path),
        audio_us_url=_media(snd.audio_us_path),
    )


@router.get(
    "/ipa-sounds",
    response={200: s.IPABoardOut, 401: ErrorOut},
    summary="Bảng âm IPA",
    description=(
        "44 âm chia nhóm (nguyên âm đơn/đôi, phụ âm vô thanh/hữu thanh, mũi & bán nguyên âm) "
        "kèm tiến độ thuần thục của người dùng. Lọc `kind` = vowel | consonant."
    ),
)
def list_ipa_sounds(request, kind: str | None = None):
    qs = m.IPASound.objects.all()
    if kind:
        qs = qs.filter(kind=kind)
    sounds = list(qs.order_by("order"))
    progress = _ipa_progress_map(request.auth)
    groups = []
    for group_kind, group in _IPA_GROUPS:
        if kind and group_kind != kind:
            continue
        members = [snd for snd in sounds if snd.group == group]
        if members:
            groups.append(
                s.IPAGroupOut(
                    code=group.value,
                    title_vi=group.label,
                    sounds=[_ipa_tile(snd, progress.get(snd.id)) for snd in members],
                )
            )
    all_total = m.IPASound.objects.count()
    return s.IPABoardOut(
        total=all_total,
        mastered=sum(1 for p in progress.values() if p.mastered_at),
        groups=groups,
    )


@router.get(
    "/ipa-sounds/{sound_id}",
    response={200: s.IPASoundDetailOut, 401: ErrorOut, 404: ErrorOut},
    summary="Chi tiết một âm IPA",
    description="Khẩu hình (môi/lưỡi + mô tả), ví dụ kèm IPA & nghĩa, cặp âm tối thiểu, mẹo, tiến độ.",
)
def get_ipa_sound(request, sound_id: int):
    snd = m.IPASound.objects.filter(id=sound_id).first()
    if snd is None:
        raise NotFound("Không tìm thấy âm")
    prog = IPASoundProgress.objects.filter(user=request.auth, sound=snd).first()

    examples = []
    for ex in snd.examples or []:
        uk, us = _ipa_word_audio(ex.get("word", ""))
        examples.append(
            s.IPAExampleOut(
                word=ex.get("word", ""),
                ipa=ex.get("ipa", ""),
                meaning_vi=ex.get("meaning_vi", ""),
                audio_uk_url=uk,
                audio_us_url=us,
            )
        )

    pair = None
    mp = snd.minimal_pair or {}
    if mp.get("other") and len(mp.get("words") or []) == 2:
        other = m.IPASound.objects.filter(symbol=mp["other"]).first()
        this_word, other_word = mp["words"]
        t_uk, t_us = _ipa_word_audio(this_word)
        o_uk, o_us = _ipa_word_audio(other_word)
        pair = s.IPAMinimalPairOut(
            hint_vi=_pair_hint(snd, other),
            this=s.IPAPairSideOut(
                id=snd.id,
                symbol=snd.symbol,
                category_vi=snd.category_vi,
                word=this_word,
                audio_uk_url=t_uk,
                audio_us_url=t_us,
            ),
            other=s.IPAPairSideOut(
                id=other.id if other else None,
                symbol=mp["other"],
                category_vi=other.category_vi if other else "",
                word=other_word,
                audio_uk_url=o_uk,
                audio_us_url=o_us,
            ),
        )

    return s.IPASoundDetailOut(
        id=snd.id,
        symbol=snd.symbol,
        kind=snd.kind,
        group=snd.group,
        category_vi=snd.category_vi,
        category_en=snd.category_en,
        description_vi=snd.description_vi,
        articulation_vi=snd.articulation_vi,
        lips_vi=snd.lips_vi,
        tongue_vi=snd.tongue_vi,
        tip_vi=snd.tip_vi,
        mouth_image_url=_media(snd.mouth_image_path),
        audio_uk_url=_media(snd.audio_uk_path),
        audio_us_url=_media(snd.audio_us_path),
        examples=examples,
        minimal_pair=pair,
        mastered=bool(prog and prog.mastered_at),
        best_score=prog.best_score if prog else 0,
        attempts=prog.attempts if prog else 0,
    )


def _pair_hint(a: m.IPASound, b: m.IPASound | None) -> str:
    if b is None:
        return "So sánh hai âm dễ nhầm"
    if a.kind == "vowel":
        return "So sánh độ dài & độ mở vòm miệng"
    if {a.group, b.group} == {"voiceless", "voiced"}:
        return "Khác nhau ở rung thanh quản"
    return "Nghe kỹ vị trí lưỡi & luồng hơi"


@router.post(
    "/ipa-sounds/{sound_id}/practice",
    response={200: s.IPAPracticeOut, 401: ErrorOut, 404: ErrorOut},
    summary="Ghi điểm luyện một âm",
    description=(
        "App chấm phát âm từ mẫu (0–100) rồi gửi lên. Điểm tốt nhất ≥ 80 → âm được đánh dấu "
        "thuần thục (tính vào tiến độ x/44)."
    ),
)
def practice_ipa_sound(request, sound_id: int, data: s.IPAPracticeIn):
    snd = m.IPASound.objects.filter(id=sound_id).first()
    if snd is None:
        raise NotFound("Không tìm thấy âm")
    prog, _ = IPASoundProgress.objects.get_or_create(user=request.auth, sound=snd)
    prog.attempts += 1
    prog.best_score = max(prog.best_score, data.score)
    newly = False
    if prog.best_score >= IPASoundProgress.MASTERY_SCORE and prog.mastered_at is None:
        prog.mastered_at = timezone.now()
        newly = True
    prog.save()
    return s.IPAPracticeOut(
        best_score=prog.best_score,
        attempts=prog.attempts,
        mastered=prog.mastered_at is not None,
        newly_mastered=newly,
        total_mastered=IPASoundProgress.objects.filter(
            user=request.auth, mastered_at__isnull=False
        ).count(),
        total=m.IPASound.objects.count(),
    )


# =============================================================== 2.7 Bundle manifest (G5)
@router.get(
    "/manifest",
    response={200: s.ManifestOut, 401: ErrorOut},
    summary="Manifest bundle nội dung",
    description="Version hiện tại + URL/checksum/size mỗi cấp. App so version → tải bundle CDN.",
)
def manifest(request):
    bundles = list(m.ContentBundle.objects.select_related("level").order_by("level__order"))
    version = max((b.version for b in bundles), default=0)
    return s.ManifestOut(
        version=version,
        levels=[
            s.ManifestLevelOut(code=b.level_id, url=b.url, checksum=b.checksum, size=b.size)
            for b in bundles
        ],
    )
