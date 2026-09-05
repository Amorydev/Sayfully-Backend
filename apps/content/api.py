"""21 endpoint nội dung học (G2). Tất cả `Bearer`.

Chỉ trả NỘI DUNG; tiến độ người dùng thuộc G4. Chi tiết A2–C2 cần Premium (🔒).
`audio_url` ghép đầy đủ từ `R2_PUBLIC_BASE`; `ipa` theo `UserProfile.accent`.
"""

from django.conf import settings
from django.db.models import Count, Q
from ninja import Query, Router

from apps.accounts.services import ensure_profile
from apps.common.exceptions import Forbidden, NotFound
from apps.common.schemas import ErrorOut

from . import models as m
from . import schemas as s

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
def _vocab_list(v: m.Vocabulary, accent: str) -> s.VocabListOut:
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


def _vocab_detail(v: m.Vocabulary, accent: str) -> s.VocabDetailOut:
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
        audio_uk_url=_media(v.audio_uk_path),
        audio_us_url=_media(v.audio_us_path),
        frequency_rank=v.frequency_rank,
        synonyms=v.synonyms or [],
        word_family=[w.headword for w in v.word_family.all()],
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
        out.spelling = s.SpellingStepOut(
            vocab_id=step.vocabulary_id,
            word=v.headword if v else p.get("word", ""),
            meaning_vi=v.meaning_vi if v else p.get("meaning_vi", ""),
            ipa=_ipa(v, accent) if v else p.get("ipa"),
            hint_vi=p.get("hint_vi", ""),
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
    description="6 cấp A1→C2 kèm mục tiêu số từ và cờ miễn phí (`is_free`, chỉ A1).",
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
        "Chi tiết cấp A2–C2 cần Premium (`premium_required`). Bước `writing` chỉ có "
        "khi bật AI."
    ),
)
def get_lesson(request, code: str):
    profile = ensure_profile(request.auth)
    lesson = m.Lesson.objects.filter(code=code).select_related("unit", "unit__level").first()
    if lesson is None:
        raise NotFound(_NOTFOUND)
    _gate(profile, lesson.unit.level)

    ai_on = getattr(settings, "AI_ENABLED", False)
    steps = lesson.steps.select_related("vocabulary", "grammar_point", "dialogue").order_by("order")
    step_outs, n_vocab, n_grammar, n_dialogue = [], 0, 0, 0
    for step in steps:
        if step.kind == m.LessonStep.Kind.WRITING and not ai_on:
            continue
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
    items = qs[offset : offset + limit]
    return s.Page(
        items=[_vocab_list(v, profile.accent) for v in items],
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
    return _vocab_detail(v, profile.accent)


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
@router.get(
    "/grammar",
    response={200: s.Page[s.GrammarListOut], 401: ErrorOut, 422: ErrorOut},
    summary="Danh sách điểm ngữ pháp",
    description="Lọc theo `level`, `category`; `q` tìm theo tiêu đề.",
)
def list_grammar(
    request,
    level: str | None = None,
    category: str | None = None,
    q: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    qs = m.GrammarPoint.objects.all()
    if level:
        qs = qs.filter(level_id=level.upper())
    if category:
        qs = qs.filter(category=category)
    if q:
        qs = qs.filter(Q(title_vi__icontains=q) | Q(title_en__icontains=q))
    qs = qs.order_by("level__order", "order")
    count = qs.count()
    items = qs[offset : offset + limit]
    return s.Page(
        items=[
            s.GrammarListOut(
                id=g.id,
                level=g.level_id,
                category=g.category,
                title_vi=g.title_vi,
                title_en=g.title_en,
                formula=g.formula,
            )
            for g in items
        ],
        count=count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/grammar/{id}",
    response={200: s.GrammarDetailOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Chi tiết điểm ngữ pháp",
    description="Công thức, bảng chia, ví dụ. Cấp A2–C2 cần Premium.",
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
    return s.GrammarDetailOut(
        id=g.id,
        level=g.level_id,
        category=g.category,
        title_vi=g.title_vi,
        title_en=g.title_en,
        formula=g.formula,
        explanation_vi=g.explanation_vi,
        common_mistake_vi=g.common_mistake_vi,
        conjugation=_conjugation(g),
        examples=_grammar_examples(g),
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
    description="Câu song ngữ (IPA + audio), từ khoá, câu hỏi. Cấp A2–C2 cần Premium.",
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
        est_minutes=r.est_minutes,
        sentences=[
            _sentence(sen.text_en, sen.ipa, sen.text_vi, sen.audio_path)
            for sen in r.sentences.all()
        ],
        keywords=[
            s.ReadingKeywordOut(
                id=k.id,
                headword=k.headword,
                ipa=_ipa(k, profile.accent),
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
    description="Cảnh + câu (audio) + câu hỏi. Cấp A2–C2 cần Premium.",
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
    description="Lọc theo `level`, `category`.",
)
def list_videos(
    request,
    level: str | None = None,
    category: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    qs = m.Video.objects.all()
    if level:
        qs = qs.filter(level_id=level.upper())
    if category:
        qs = qs.filter(category=category)
    qs = qs.order_by("level__order", "id")
    count = qs.count()
    items = qs[offset : offset + limit]
    return s.Page(
        items=[
            s.VideoListOut(
                id=vd.id,
                youtube_id=vd.youtube_id,
                level=vd.level_id,
                title_vi=vd.title_vi,
                title_en=vd.title_en,
                category=vd.category,
                duration_sec=vd.duration_sec,
                thumbnail_url=_media(vd.thumbnail_path),
                is_free=vd.is_free,
            )
            for vd in items
        ],
        count=count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/videos/{id}",
    response={200: s.VideoDetailOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Chi tiết video kèm phụ đề",
    description="Phụ đề song ngữ có timestamp + IPA. Cấp A2–C2 cần Premium.",
)
def get_video(request, id: int):
    profile = ensure_profile(request.auth)
    vd = m.Video.objects.filter(id=id).select_related("level").prefetch_related("subtitles").first()
    if vd is None:
        raise NotFound(_NOTFOUND)
    _gate(profile, vd.level)
    return s.VideoDetailOut(
        id=vd.id,
        youtube_id=vd.youtube_id,
        level=vd.level_id,
        title_vi=vd.title_vi,
        title_en=vd.title_en,
        category=vd.category,
        duration_sec=vd.duration_sec,
        subtitles=[
            s.VideoSubtitleOut(
                order=sub.order,
                start_ms=sub.start_ms,
                end_ms=sub.end_ms,
                text_en=sub.text_en,
                ipa=sub.ipa,
                text_vi=sub.text_vi,
            )
            for sub in vd.subtitles.all()
        ],
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
    description="Câu mục tiêu + IPA + audio bản xứ. Cấp A2–C2 cần Premium.",
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
            )
            for sen in dk.sentences.all()
        ],
    )


# =============================================================== 2.6 Tra cứu
@router.get(
    "/roots",
    response={200: list[s.WordRootOut], 401: ErrorOut},
    summary="Danh sách gốc từ (tiền tố / gốc / hậu tố)",
    description="Lọc theo `kind`; `q` tìm theo ký tự gốc.",
)
def list_roots(request, kind: str | None = None, q: str | None = None):
    qs = m.WordRoot.objects.annotate(n=Count("examples"))
    if kind:
        qs = qs.filter(kind=kind)
    if q:
        qs = qs.filter(text__icontains=q)
    return [
        s.WordRootOut(
            id=r.id,
            kind=r.kind,
            text=r.text,
            meaning_vi=r.meaning_vi,
            group_vi=r.group_vi,
            example_count=r.n,
        )
        for r in qs.order_by("kind", "text")
    ]


@router.get(
    "/roots/{id}",
    response={200: s.WordRootDetailOut, 401: ErrorOut, 404: ErrorOut},
    summary="Chi tiết gốc từ kèm từ ví dụ",
    description="Nghĩa, mẹo nhớ, và các từ vựng chứa gốc này.",
)
def get_root(request, id: int):
    r = m.WordRoot.objects.filter(id=id).prefetch_related("examples").first()
    if r is None:
        raise NotFound(_NOTFOUND)
    profile = ensure_profile(request.auth)
    return s.WordRootDetailOut(
        id=r.id,
        kind=r.kind,
        text=r.text,
        meaning_vi=r.meaning_vi,
        group_vi=r.group_vi,
        mnemonic_vi=r.mnemonic_vi,
        examples=[
            s.RootExampleOut(
                id=v.id,
                headword=v.headword,
                ipa=_ipa(v, profile.accent),
                meaning_vi=v.meaning_vi,
            )
            for v in r.examples.all()
        ],
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


@router.get(
    "/ipa-sounds",
    response={200: list[s.IPASoundOut], 401: ErrorOut},
    summary="Bảng âm IPA",
    description="Lọc theo `kind` (vowel / consonant). Kèm khẩu hình và từ mẫu.",
)
def list_ipa_sounds(request, kind: str | None = None):
    qs = m.IPASound.objects.all()
    if kind:
        qs = qs.filter(kind=kind)
    return [
        s.IPASoundOut(
            id=snd.id,
            symbol=snd.symbol,
            kind=snd.kind,
            description_vi=snd.description_vi,
            articulation_vi=snd.articulation_vi,
            mouth_image_url=_media(snd.mouth_image_path),
            sample_words=snd.sample_words or [],
            minimal_pair=snd.minimal_pair or {},
            audio_uk_url=_media(snd.audio_uk_path),
            audio_us_url=_media(snd.audio_us_path),
        )
        for snd in qs.order_by("kind", "order")
    ]


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
