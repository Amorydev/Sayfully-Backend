"""Gia sư AI (C17/C44/C33) — LLM được mock qua `apps.ai.llm.complete`."""

import json

import pytest

from apps.accounts.services import ensure_profile
from apps.ai import llm
from apps.ai.management.commands.seed_scenarios import seed_roleplay_scenarios
from apps.ai.models import AIConversation, AIQuota, RoleplayScenario
from apps.content.models import GrammarPoint, Level
from apps.learning.models import NotebookEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def token(api, user, password) -> str:
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


@pytest.fixture(autouse=True)
def _ai_on(settings):
    settings.AI_ENABLED = True
    settings.AI_PROVIDER = "mock"
    settings.AI_FREE_TURNS = 3
    settings.AI_PREMIUM_TURNS = 200


@pytest.fixture
def scenarios():
    seed_roleplay_scenarios()
    return list(RoleplayScenario.objects.all())


@pytest.fixture
def grammar():
    a1 = Level.objects.create(code="A1", name_vi="Sơ cấp", order=1, is_free=True)
    return GrammarPoint.objects.create(
        level=a1, order=1, title_vi="Quá khứ đơn", explanation_vi="..."
    )


def _turn(reply="Nice! Tell me more?", correction=None, goals=(), end=False):
    return llm.Completion(
        text=json.dumps(
            {
                "reply_en": reply,
                "reply_vi": "Hay quá!",
                "correction": correction,
                "vocab": ["beach"],
                "praise_vi": None,
                "suggested_replies": [{"en": "I went home.", "vi": "Mình về nhà."}],
                "goals_completed": list(goals),
                "suggested_end": end,
            }
        ),
        tokens_in=10,
        tokens_out=5,
    )


# --------------------------------------------------------------- hub
def test_hub_tra_quota_kich_ban_va_chu_de(api, token, user, scenarios):
    NotebookEntry.objects.create(user=user, custom_word="luggage", custom_meaning="hành lý")
    r = api.get("/ai/home", token=token)
    assert r.status_code == 200
    body = r.json()
    assert body["quota"] == {
        "used": 0,
        "limit": 3,
        "left": 3,
        "is_premium": False,
        "resets_at": body["quota"]["resets_at"],
    }
    assert body["continue_session"] is None
    assert len(body["scenarios"]) == len(scenarios)
    cafe = next(sc for sc in body["scenarios"] if sc["scene"] == "cafe")
    assert cafe["locked"] is False and cafe["goal_count"] == 5
    doctor = next(sc for sc in body["scenarios"] if sc["scene"] == "doctor")
    assert doctor["locked"] is True
    assert body["topics"][0]["code"] == "travel"
    assert body["notebook_words"] == ["luggage"]


def test_feature_tat_tra_503(api, token, settings):
    settings.AI_ENABLED = False
    r = api.post("/ai/conversations", {"kind": "tutor", "topic": "travel"}, token=token)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "feature_disabled"


# --------------------------------------------------------------- tutor
def test_tao_hoi_thoai_long_mo_loi_khong_tru_quota(api, token, user):
    r = api.post("/ai/conversations", {"kind": "tutor", "topic": "travel"}, token=token)
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["kind"] == "tutor"
    assert body["title_vi"] == "Nói chuyện tự do: Du lịch"
    assert body["messages"][0]["role"] == "assistant"
    assert body["messages"][0]["reply_vi"]  # A1 có dịch
    assert body["messages"][0]["suggested_replies"]
    assert body["quota"]["used"] == 0
    assert body["turns"] == 0


def test_gui_luot_sua_loi_tru_quota_va_idempotent(api, token, user, grammar, monkeypatch):
    conv = api.post("/ai/conversations", {"kind": "tutor", "topic": "travel"}, token=token).json()
    calls = []

    def fake(system, messages, **kw):
        calls.append(messages[-1]["content"])
        assert "<context>" in system
        assert f"{grammar.id}: Quá khứ đơn" in system
        return _turn(
            correction={
                "original": "I go to Da Nang last summer",
                "corrected": "I went to Da Nang last summer",
                "note_vi": "Quá khứ đơn: go → went",
                "grammar_id": grammar.id,
            }
        )

    monkeypatch.setattr(llm, "complete", fake)
    payload = {"text": "I go to Da Nang last summer", "client_msg_id": "m1", "via": "voice"}
    r = api.post(f"/ai/conversations/{conv['id']}/messages", payload, token=token)
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["message"]["text"] == "Nice! Tell me more?"
    assert body["message"]["correction"]["corrected"] == "I went to Da Nang last summer"
    assert body["message"]["correction"]["grammar_id"] == grammar.id
    assert body["message"]["vocab"] == [{"word": "beach", "vocab_id": None, "saved": False}]
    assert body["turns"] == 1
    assert body["quota"]["used"] == 1 and body["quota"]["left"] == 2

    # gửi lại cùng client_msg_id → trả lượt cũ, không gọi LLM, không trừ quota
    r2 = api.post(f"/ai/conversations/{conv['id']}/messages", payload, token=token)
    assert r2.status_code == 200
    assert r2.json()["message"]["id"] == body["message"]["id"]
    assert r2.json()["quota"]["used"] == 1
    assert len(calls) == 1

    # tải lại hội thoại: user message mang correction
    r3 = api.get(f"/ai/conversations/{conv['id']}", token=token)
    msgs = r3.json()["messages"]
    assert [m["role"] for m in msgs] == ["assistant", "user", "assistant"]
    assert msgs[1]["correction"]["note_vi"] == "Quá khứ đơn: go → went"


def test_het_quota_tra_429(api, token, user):
    conv = api.post("/ai/conversations", {"kind": "tutor", "topic": "travel"}, token=token).json()
    for i in range(3):
        r = api.post(
            f"/ai/conversations/{conv['id']}/messages",
            {"text": f"Hello {i}", "client_msg_id": f"c{i}"},
            token=token,
        )
        assert r.status_code == 200
    r = api.post(
        f"/ai/conversations/{conv['id']}/messages",
        {"text": "one more", "client_msg_id": "c9"},
        token=token,
    )
    assert r.status_code == 429
    err = r.json()["error"]
    assert err["code"] == "ai_quota_exceeded"
    assert AIQuota.objects.get(user=user).messages_used == 3
    # Premium được nới
    p = ensure_profile(user)
    p.is_premium = True
    p.save()
    r = api.post(
        f"/ai/conversations/{conv['id']}/messages",
        {"text": "one more", "client_msg_id": "c9"},
        token=token,
    )
    assert r.status_code == 200


def test_upstream_loi_khong_tru_quota(api, token, user, monkeypatch):
    conv = api.post("/ai/conversations", {"kind": "tutor", "topic": "travel"}, token=token).json()

    def boom(system, messages, **kw):
        raise llm.AIUpstreamError("Long đang bận")

    monkeypatch.setattr(llm, "complete", boom)
    r = api.post(
        f"/ai/conversations/{conv['id']}/messages",
        {"text": "Hi", "client_msg_id": "x"},
        token=token,
    )
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "ai_upstream"
    assert not AIQuota.objects.filter(user=user, messages_used__gt=0).exists()
    assert AIConversation.objects.get(id=conv["id"]).messages.filter(role="user").count() == 0


def test_ket_thuc_thuong_khi_du_luot(api, token, user, settings):
    settings.AI_FREE_TURNS = 20
    conv = api.post("/ai/conversations", {"kind": "tutor", "topic": "travel"}, token=token).json()
    for i in range(6):
        text = "I go to the beach" if i == 0 else f"I like it {i}"
        api.post(
            f"/ai/conversations/{conv['id']}/messages",
            {"text": text, "client_msg_id": f"t{i}"},
            token=token,
        )
    r = api.post(f"/ai/conversations/{conv['id']}/end", token=token)
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["rewarded"] is True
    assert body["xp"] == 30 and body["coins"] == 15
    assert body["turns"] == 6
    assert body["mistake_count"] == 1
    assert body["top_mistakes"][0]["corrected"] == "I went to the beach"
    assert body["score"] == 92
    assert body["vocab"][0]["word"] == "summer"
    p = ensure_profile(user)
    assert p.xp_total == 30 and p.coins == 15
    # idempotent
    r2 = api.post(f"/ai/conversations/{conv['id']}/end", token=token)
    assert r2.json()["xp"] == 30
    assert ensure_profile(user).xp_total == 30
    # gửi thêm lượt → 409
    r3 = api.post(
        f"/ai/conversations/{conv['id']}/messages",
        {"text": "again", "client_msg_id": "z"},
        token=token,
    )
    assert r3.status_code == 409
    assert r3.json()["error"]["code"] == "conversation_ended"
    # hub hiện lịch sử
    hub = api.get("/ai/home", token=token).json()
    assert hub["history"][0]["conversation_id"] == conv["id"]
    assert hub["history"][0]["score"] == 92


def test_ket_thuc_som_khong_thuong(api, token, user):
    conv = api.post("/ai/conversations", {"kind": "tutor", "topic": "travel"}, token=token).json()
    api.post(
        f"/ai/conversations/{conv['id']}/messages",
        {"text": "Hello", "client_msg_id": "a"},
        token=token,
    )
    body = api.post(f"/ai/conversations/{conv['id']}/end", token=token).json()
    assert body["rewarded"] is False and body["xp"] == 0
    assert body["min_turns_for_reward"] == 6
    assert ensure_profile(user).xp_total == 0


# --------------------------------------------------------------- roleplay
def test_dong_vai_premium_bi_khoa(api, token, scenarios):
    doctor = next(sc for sc in scenarios if sc.scene == "doctor")
    r = api.post("/ai/conversations", {"kind": "roleplay", "scenario_id": doctor.id}, token=token)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "premium_required"


def test_dong_vai_muc_tieu_va_thuong_bonus(api, token, user, scenarios, settings, monkeypatch):
    settings.AI_FREE_TURNS = 20
    cafe = next(sc for sc in scenarios if sc.scene == "cafe")
    r = api.post("/ai/conversations", {"kind": "roleplay", "scenario_id": cafe.id}, token=token)
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["scenario"]["goals"] == cafe.goals
    assert body["goals_state"] == [False] * 5

    step = {"n": 0}

    def fake(system, messages, **kw):
        if "SUMMARY" in system:
            return llm.Completion(
                text=json.dumps(
                    {"score": 96, "verdict_vi": "Đỉnh!", "summary_vi": "Tốt.", "top_mistakes": []}
                ),
                tokens_in=0,
                tokens_out=0,
            )
        assert "ROLEPLAY MODE" in system
        i = step["n"]
        step["n"] += 1
        return _turn(reply="Sure!", goals=[i] if i < 5 else [], end=False)

    monkeypatch.setattr(llm, "complete", fake)
    lines = [
        "Good morning!",
        "Can I have a latte?",
        "Large please",
        "How much is it?",
        "Thank you!",
    ]
    for i, line in enumerate(lines):
        t = api.post(
            f"/ai/conversations/{body['id']}/messages",
            {"text": line, "client_msg_id": f"g{i}"},
            token=token,
        ).json()
    assert t["goals_state"] == [True] * 5
    assert t["suggested_end"] is True
    assert t["turns"] == 5  # đủ mục tiêu → thưởng dù chưa đủ 6 lượt

    s = api.post(f"/ai/conversations/{body['id']}/end", token=token).json()
    assert s["goals_all_done"] is True
    assert [g["evidence"] for g in s["goals"]] == lines[:5]
    assert s["goals"][1]["hint_en"] == "Can I have an iced latte, please?"
    assert s["xp"] == cafe.xp_reward + 50 and s["bonus_xp"] == 50
    assert s["coins"] == cafe.coin_reward
    assert s["score"] == 96
    assert s["next_scenario_id"] is not None

    hub = api.get("/ai/home", token=token).json()
    sc = next(x for x in hub["scenarios"] if x["id"] == cafe.id)
    assert sc["completed"] is True and sc["best_score"] == 96


def test_tiep_tuc_phien_do(api, token, user):
    conv = api.post("/ai/conversations", {"kind": "tutor", "topic": "food"}, token=token).json()
    hub = api.get("/ai/home", token=token).json()
    assert hub["continue_session"]["conversation_id"] == conv["id"]
    assert hub["continue_session"]["title_vi"] == "Nói chuyện tự do: Ẩm thực"


def test_home_quota_va_thu_thach_noi_voi_long(api, token, user, settings):
    from apps.gamification.models import Challenge

    settings.AI_FREE_TURNS = 20
    Challenge.objects.create(
        code="daily_ai_talk",
        scope="daily",
        metric="ai_turns",
        title_vi="Nói 5 câu với Long",
        target=5,
        reward_coins=20,
    )
    conv = api.post("/ai/conversations", {"kind": "tutor", "topic": "travel"}, token=token).json()
    for i in range(3):
        api.post(
            f"/ai/conversations/{conv['id']}/messages",
            {"text": f"Hi {i}", "client_msg_id": f"h{i}"},
            token=token,
        )
    # phiên ngắn: không thưởng nhưng vẫn ghi lượt nói cho thử thách
    end = api.post(f"/ai/conversations/{conv['id']}/end", token=token).json()
    assert end["rewarded"] is False
    home = api.get("/home", token=token).json()
    assert home["ai_tutor"] == {
        "enabled": True,
        "quota_left": 17,
        "quota_limit": 20,
        "resets_at": home["ai_tutor"]["resets_at"],
    }
    task = next(c for c in home["challenges"]["items"] if c["title"] == "Nói 5 câu với Long")
    assert task["current"] == 3 and task["target"] == 5 and task["reward_coins"] == 20
    assert ensure_profile(user).streak_current == 1  # có hoạt động trong ngày
