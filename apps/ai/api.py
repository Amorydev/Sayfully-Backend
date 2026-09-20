"""Gia sư AI — router `/ai` (Bearer).

- C44 hub: `GET /ai/home`, `GET /ai/scenarios/{id}`
- C17 trò chuyện: `POST /ai/conversations`, `GET|POST /ai/conversations/{id}[/messages]`
- C33 tổng kết: `POST /ai/conversations/{id}/end`, `GET /ai/conversations/{id}/summary`
Lỗi riêng: 429 `ai_quota_exceeded` · 409 `conversation_ended` · 503 `feature_disabled` · 502 `ai_upstream`.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone as djtz
from ninja import Router

from apps.accounts.services import ensure_profile
from apps.common.exceptions import Conflict, NotFound
from apps.common.schemas import ErrorOut
from apps.learning import services as learn

from . import schemas as s
from . import services as svc
from .models import AIConversation, AIMessage, RoleplayScenario
from .scenarios_data import TOPICS

router = Router()


# --------------------------------------------------------------- helpers
def _quota(profile) -> s.QuotaOut:
    q = svc.quota_for(profile)
    limit = svc.quota_limit(profile)
    return s.QuotaOut(
        used=q.messages_used,
        limit=limit,
        left=max(0, limit - q.messages_used),
        is_premium=profile.is_premium,
        resets_at=(learn.local_today(profile) + timedelta(days=1)).isoformat(),
    )


def _media(path: str | None) -> str | None:
    if not path:
        return None
    return f"{settings.R2_PUBLIC_BASE.rstrip('/')}/{path}"


def _scenario(sc: RoleplayScenario, profile, best: dict[int, int]) -> s.ScenarioOut:
    return s.ScenarioOut(
        id=sc.id,
        level=sc.level,
        scene=sc.scene,
        topic=sc.topic,
        title_vi=sc.title_vi,
        description_vi=sc.description_vi,
        goal_count=len(sc.goals),
        duration_min=sc.duration_min,
        is_premium=sc.is_premium,
        locked=sc.is_premium and not profile.is_premium,
        completed=sc.id in best,
        best_score=best.get(sc.id),
        background_url=_media(sc.thumbnail_path),
        xp_reward=sc.xp_reward,
        coin_reward=sc.coin_reward,
    )


def _scenario_detail(sc: RoleplayScenario, profile, best: dict[int, int]) -> s.ScenarioDetailOut:
    base = _scenario(sc, profile, best)
    return s.ScenarioDetailOut(
        **base.dict(),
        ai_role_vi=sc.ai_role_vi,
        user_role_vi=sc.user_role_vi,
        goals=list(sc.goals),
        goal_hints=list(sc.goal_hints),
        tip_vi=sc.tip_vi,
    )


def _best_scores(user) -> dict[int, int]:
    best: dict[int, int] = {}
    qs = AIConversation.objects.filter(
        user=user, kind=AIConversation.Kind.ROLEPLAY, ended_at__isnull=False, scenario__isnull=False
    ).values_list("scenario_id", "result")
    for sid, result in qs:
        score = (result or {}).get("score")
        if score is None:
            continue
        best[sid] = max(best.get(sid, 0), int(score))
    return best


def _message(m: AIMessage, user, user_msg: AIMessage | None = None) -> s.MessageOut:
    meta = m.meta or {}
    if m.role == "assistant":
        return s.MessageOut(
            id=m.id,
            role="assistant",
            text=m.content,
            reply_vi=meta.get("reply_vi"),
            vocab=[s.VocabOut(**v) for v in svc.vocab_status(user, meta.get("vocab") or [])],
            praise_vi=meta.get("praise_vi"),
            suggested_replies=[
                s.SuggestedReplyOut(**r) for r in meta.get("suggested_replies") or []
            ],
            on_topic=bool(meta.get("on_topic", True)),
            topic_note_vi=meta.get("topic_note_vi"),
            created_at=m.created_at.isoformat(),
        )
    corr = meta.get("correction")
    return s.MessageOut(
        id=m.id,
        role="user",
        text=m.content,
        correction=s.CorrectionOut(**corr) if corr else None,
        created_at=m.created_at.isoformat(),
    )


def _history_item(c: AIConversation) -> s.HistoryItemOut:
    r = c.result or {}
    return s.HistoryItemOut(
        conversation_id=c.id,
        kind=c.kind,
        title_vi=c.title_vi,
        turns=c.turn_count,
        mistake_count=int(r.get("mistake_count") or 0),
        score=r.get("score"),
        ended_at=c.ended_at.isoformat(),
    )


def _conversation_out(conv: AIConversation, user, profile) -> s.ConversationOut:
    msgs = list(conv.messages.exclude(role="system").order_by("created_at", "id"))
    last = next((m for m in reversed(msgs) if m.role == "assistant"), None)
    return s.ConversationOut(
        id=conv.id,
        kind=conv.kind,
        title_vi=conv.title_vi,
        topic=conv.topic,
        scenario=_scenario_detail(conv.scenario, profile, _best_scores(user))
        if conv.scenario
        else None,
        goals_state=list(conv.goals_state),
        turns=conv.turn_count,
        ended=conv.ended_at is not None,
        messages=[_message(m, user) for m in msgs],
        suggested_end=bool((last.meta or {}).get("suggested_end")) if last else False,
        quota=_quota(profile),
    )


# --------------------------------------------------------------- hub
@router.get(
    "/home",
    response={200: s.AiHubOut, 401: ErrorOut},
    summary="Hub Gia sư AI: quota, phiên dở, kịch bản đóng vai, lịch sử",
    description="`continue_session` là phiên chưa kết thúc gần nhất (nếu có). Kịch bản trả đủ mọi cấp, "
    "app lọc theo segmented A1/A2/B1. `locked` = kịch bản Premium và người dùng chưa Premium.",
)
def ai_home(request):
    user = request.auth
    profile = ensure_profile(user)
    best = _best_scores(user)
    open_conv = (
        AIConversation.objects.filter(user=user, ended_at__isnull=True)
        .select_related("scenario")
        .order_by("-created_at")
        .first()
    )
    cont = None
    if open_conv is not None:
        cont = s.ContinueOut(
            conversation_id=open_conv.id,
            kind=open_conv.kind,
            title_vi=open_conv.title_vi,
            goals_done=sum(1 for g in open_conv.goals_state if g),
            goals_total=len(open_conv.goals_state),
            turns=open_conv.turn_count,
            minutes_ago=max(0, int((djtz.now() - open_conv.created_at).total_seconds() // 60)),
            scene=open_conv.scenario.scene if open_conv.scenario else "",
            background_url=_media(open_conv.scenario.thumbnail_path) if open_conv.scenario else None,
        )
    history = AIConversation.objects.filter(user=user, ended_at__isnull=False).order_by(
        "-ended_at"
    )[:3]
    return s.AiHubOut(
        quota=_quota(profile),
        continue_session=cont,
        scenarios=[_scenario(sc, profile, best) for sc in RoleplayScenario.objects.all()],
        history=[_history_item(c) for c in history],
        topics=[
            s.TopicOut(code=t["code"], emoji=t["emoji"], title_vi=t["title_vi"]) for t in TOPICS
        ],
        notebook_words=svc.notebook_words(user, limit=3),
    )


@router.get(
    "/scenarios/{id}",
    response={200: s.ScenarioDetailOut, 401: ErrorOut, 404: ErrorOut},
    summary="Chi tiết kịch bản đóng vai (sheet xem trước)",
)
def scenario_detail(request, id: int):
    sc = RoleplayScenario.objects.filter(id=id).first()
    if sc is None:
        raise NotFound("Không tìm thấy kịch bản")
    return _scenario_detail(sc, ensure_profile(request.auth), _best_scores(request.auth))


# --------------------------------------------------------------- conversations
@router.post(
    "/conversations",
    response={
        200: s.ConversationOut,
        401: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        429: ErrorOut,
        502: ErrorOut,
        503: ErrorOut,
    },
    summary="Tạo hội thoại mới; Long nói câu mở đầu",
    description="`kind=tutor` cần `topic` (mã trong `/ai/home.topics`); `kind=roleplay` cần `scenario_id`. "
    "Câu mở đầu không tính vào quota.",
)
def start_conversation(request, data: s.StartConversationIn):
    conv, _ = svc.start_conversation(
        request.auth,
        kind=data.kind,
        scenario_id=data.scenario_id,
        topic=data.topic,
        use_notebook=data.use_notebook,
    )
    return _conversation_out(conv, request.auth, ensure_profile(request.auth))


@router.get(
    "/conversations/{id}",
    response={200: s.ConversationOut, 401: ErrorOut, 404: ErrorOut},
    summary="Tải lại hội thoại (tiếp tục phiên dở)",
)
def get_conversation(request, id: int):
    conv = svc.get_conversation(request.auth, id)
    return _conversation_out(conv, request.auth, ensure_profile(request.auth))


@router.post(
    "/conversations/{id}/messages",
    response={
        200: s.TurnOut,
        401: ErrorOut,
        404: ErrorOut,
        409: ErrorOut,
        429: ErrorOut,
        502: ErrorOut,
        503: ErrorOut,
    },
    summary="Gửi một lượt nói của người học, nhận trả lời + sửa lỗi",
    description="`client_msg_id` idempotent: gửi lại cùng id trả đúng lượt cũ, không trừ quota. "
    "Lượt lỗi upstream (502) không trừ quota.",
)
def send_turn(request, id: int, data: s.SendTurnIn):
    turn = svc.send_turn(
        request.auth, id, text=data.text.strip(), client_msg_id=data.client_msg_id, via=data.via
    )
    conv = svc.get_conversation(request.auth, id)
    user_msg = conv.messages.filter(role="user", id__lt=turn.message.id).order_by("-id").first()
    msg = _message(turn.message, request.auth)
    reply_user = _message(user_msg, request.auth) if user_msg else None
    if reply_user is not None:
        msg.correction = reply_user.correction
    return s.TurnOut(
        message=msg,
        goals_state=list(conv.goals_state),
        goals_completed=turn.data["goals_completed"],
        suggested_end=turn.data["suggested_end"],
        turns=conv.turn_count,
        quota=_quota(ensure_profile(request.auth)),
    )


def _summary_out(conv: AIConversation, user) -> s.SummaryOut:
    r = conv.result or {}
    goals = []
    if conv.scenario:
        hints = list(conv.scenario.goal_hints) + [""] * len(conv.scenario.goals)
        for i, label in enumerate(conv.scenario.goals):
            done = bool(conv.goals_state[i]) if i < len(conv.goals_state) else False
            evidence = conv.goal_evidence[i] if i < len(conv.goal_evidence) else None
            goals.append(
                s.GoalResultOut(label_vi=label, done=done, evidence=evidence, hint_en=hints[i])
            )
    next_id = None
    if conv.scenario:
        nxt = (
            RoleplayScenario.objects.filter(
                level=conv.scenario.level, order__gt=conv.scenario.order
            )
            .order_by("order")
            .first()
        ) or RoleplayScenario.objects.exclude(id=conv.scenario.id).first()
        next_id = nxt.id if nxt else None
    return s.SummaryOut(
        conversation_id=conv.id,
        kind=conv.kind,
        title_vi=conv.title_vi,
        score=r.get("score"),
        verdict_vi=r.get("verdict_vi") or "",
        summary_vi=r.get("summary_vi") or "",
        turns=conv.turn_count,
        minutes=int(r.get("minutes") or 1),
        mistake_count=int(r.get("mistake_count") or 0),
        top_mistakes=[s.CorrectionOut(**m) for m in r.get("top_mistakes") or []],
        vocab=[
            s.VocabOut(**v)
            for v in svc.vocab_status(user, [v["word"] for v in r.get("vocab") or []])
        ],
        goals=goals,
        goals_all_done=bool(goals) and all(g.done for g in goals),
        xp=int(r.get("xp") or 0),
        bonus_xp=int(r.get("bonus_xp") or 0),
        coins=int(r.get("coins") or 0),
        rewarded=bool(r.get("rewarded")),
        min_turns_for_reward=svc.MIN_TURNS_FOR_REWARD,
        streak_days=int(r.get("streak_days") or 0),
        next_scenario_id=next_id,
    )


@router.post(
    "/conversations/{id}/end",
    response={200: s.SummaryOut, 401: ErrorOut, 404: ErrorOut, 502: ErrorOut, 503: ErrorOut},
    summary="Kết thúc hội thoại: tổng kết, 3 lỗi cần nhớ, thưởng XP/xu",
    description=f"Thưởng khi ≥ {svc.MIN_TURNS_FOR_REWARD} lượt hoặc đóng vai đạt đủ mục tiêu (+{svc.ROLEPLAY_BONUS_XP} XP). "
    "Gọi lại trên hội thoại đã kết thúc trả lại tổng kết cũ (idempotent).",
)
def end_conversation(request, id: int):
    conv = svc.end_conversation(request.auth, id)
    return _summary_out(conv, request.auth)


@router.get(
    "/conversations/{id}/summary",
    response={200: s.SummaryOut, 401: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    summary="Xem lại tổng kết của hội thoại đã kết thúc",
)
def conversation_summary(request, id: int):
    conv = svc.get_conversation(request.auth, id)
    if conv.ended_at is None:
        raise Conflict("Hội thoại chưa kết thúc", code="conversation_open")
    return _summary_out(conv, request.auth)


@router.get(
    "/conversations",
    response={200: s.HistoryPageOut, 401: ErrorOut},
    summary="Lịch sử hội thoại đã kết thúc",
)
def list_conversations(request, limit: int = 20, offset: int = 0):
    qs = AIConversation.objects.filter(user=request.auth, ended_at__isnull=False).order_by(
        "-ended_at"
    )
    limit = max(1, min(limit, 50))
    return s.HistoryPageOut(
        items=[_history_item(c) for c in qs[offset : offset + limit]],
        count=qs.count(),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/quota", response={200: s.QuotaOut, 401: ErrorOut}, summary="Lượt nói chuyện còn lại hôm nay"
)
def quota(request):
    return _quota(ensure_profile(request.auth))
