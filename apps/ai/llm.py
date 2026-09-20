"""Gọi LLM cho Gia sư AI.

Provider `openai_compat`: POST `{AI_BASE_URL}/chat/completions` (DeepSeek trực tiếp hoặc qua
OpenRouter). Provider `mock`: trả lời mẫu có cấu trúc để dựng UI / chạy test không cần key.
Hàm duy nhất bên ngoài dùng là :func:`complete` — service chỉ quan tâm chuỗi JSON trả về.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import requests
from django.conf import settings

from apps.common.exceptions import AppError

logger = logging.getLogger(__name__)


class AIUpstreamError(AppError):
    status_code = 502
    code = "ai_upstream"


@dataclass
class Completion:
    text: str
    tokens_in: int
    tokens_out: int


def complete(system: str, messages: list[dict], *, max_tokens: int = 600) -> Completion:
    """`messages` = [{"role": "user"|"assistant", "content": str}, ...]; trả về text JSON."""
    provider = settings.AI_PROVIDER
    if provider == "mock":
        return _mock(system, messages)
    if provider == "openai_compat":
        return _openai_compat(system, messages, max_tokens=max_tokens)
    raise AIUpstreamError(f"AI_PROVIDER không hỗ trợ: {provider}")


def _openai_compat(system: str, messages: list[dict], *, max_tokens: int) -> Completion:
    if not settings.AI_API_KEY:
        raise AIUpstreamError("Thiếu AI_API_KEY", code="config_missing")
    payload = {
        "model": settings.AI_MODEL,
        "messages": [{"role": "system", "content": system}, *messages],
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {settings.AI_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://sayfully.app",
        "X-Title": "Sayfully",
    }
    try:
        resp = requests.post(
            f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
            timeout=settings.AI_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("ai upstream request failed: %s", exc)
        raise AIUpstreamError("Long đang bận, thử lại sau vài giây") from exc
    if resp.status_code >= 400:
        logger.warning("ai upstream %s: %s", resp.status_code, resp.text[:300])
        raise AIUpstreamError("Long đang bận, thử lại sau vài giây")
    body = resp.json()
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIUpstreamError("Phản hồi AI không hợp lệ") from exc
    usage = body.get("usage") or {}
    return Completion(
        text=text,
        tokens_in=int(usage.get("prompt_tokens") or 0),
        tokens_out=int(usage.get("completion_tokens") or 0),
    )


# --------------------------------------------------------------- mock
_MOCK_QUESTIONS = [
    "Hi! Where did you go last summer? 🌴",
    "Nice! What did you do there?",
    "Sounds fun! Who did you go with?",
    "What food did you eat on the trip?",
    "Do you want to go back there next year?",
    "What is your favourite place in Vietnam?",
]
_MOCK_VI = [
    "Chào bạn! Hè vừa rồi bạn đi đâu?",
    "Tuyệt! Bạn đã làm gì ở đó?",
    "Vui ghê! Bạn đi cùng ai?",
    "Bạn ăn món gì trong chuyến đi?",
    "Bạn có muốn quay lại đó năm sau không?",
    "Nơi bạn thích nhất ở Việt Nam là đâu?",
]
_MOCK_FIXES = {
    " go ": (" went ", "Quá khứ đơn: go → went"),
    " eat ": (" ate ", "Quá khứ đơn: eat → ate"),
    " is ": (" was ", "Quá khứ đơn: is → was"),
    "i am go": ("i went", "Kể chuyện đã xảy ra dùng quá khứ đơn"),
}


def _mock(system: str, messages: list[dict]) -> Completion:
    if "VIDEO_TRANSLATE" in system:
        return Completion(text=json.dumps(_mock_video_translate(messages)), tokens_in=0, tokens_out=0)
    user_turns = [m for m in messages if m["role"] == "user" and not m["content"].startswith("(")]
    if "SUMMARY" in system:
        return Completion(text=json.dumps(_mock_summary(user_turns)), tokens_in=0, tokens_out=0)
    idx = min(len(user_turns), len(_MOCK_QUESTIONS) - 1)
    last = user_turns[-1]["content"].strip() if user_turns else ""
    correction = None
    padded = f" {last.lower()} "
    for wrong, (right, note) in _MOCK_FIXES.items():
        if wrong in padded:
            correction = {
                "original": last,
                "corrected": _mock_fix(last, wrong, right),
                "note_vi": note,
                "grammar_id": None,
            }
            break
    goals_completed = []
    if "ROLEPLAY" in system and user_turns:
        goals_completed = [len(user_turns) - 1]
    out = {
        "reply_en": _MOCK_QUESTIONS[idx],
        "reply_vi": _MOCK_VI[idx],
        "correction": correction,
        "vocab": ["summer", "beach"] if idx == 0 else [],
        "praise_vi": "Bạn vừa dùng 'beach' — từ trong Sổ tay!" if "beach" in padded else None,
        "suggested_replies": [
            {"en": "I went to the beach with my family.", "vi": "Mình đi biển với gia đình."},
            {"en": "I stayed at home and watched movies.", "vi": "Mình ở nhà xem phim."},
            {"en": "I visited my grandparents.", "vi": "Mình về thăm ông bà."},
        ],
        "goals_completed": goals_completed,
        "on_topic": True,
        "suggested_end": len(user_turns) >= 15,
    }
    return Completion(text=json.dumps(out), tokens_in=0, tokens_out=0)


def _mock_fix(sentence: str, wrong: str, right: str) -> str:
    fixed = re.sub(re.escape(wrong.strip()), right.strip(), sentence, count=1, flags=re.IGNORECASE)
    return fixed[0].upper() + fixed[1:]


def _mock_summary(user_turns: list[dict]) -> dict:
    mistakes = []
    for m in user_turns:
        padded = f" {m['content'].lower()} "
        for wrong, (right, note) in _MOCK_FIXES.items():
            if wrong in padded and len(mistakes) < 3:
                mistakes.append(
                    {
                        "original": m["content"],
                        "corrected": _mock_fix(m["content"], wrong, right),
                        "note_vi": note,
                        "grammar_id": None,
                    }
                )
    score = max(40, 100 - 8 * len(mistakes))
    return {
        "score": score,
        "verdict_vi": "Trôi chảy hơn hôm qua rồi đó!" if score >= 80 else "Cố thêm chút nữa nhé!",
        "summary_vi": (
            "Bạn trả lời tự nhiên và dùng đúng thì hiện tại. Cần chú ý thì quá khứ đơn khi kể "
            "chuyện. Mai mình nói tiếp về chuyến đi của bạn nhé?"
        ),
        "top_mistakes": mistakes,
    }


def _mock_video_translate(messages: list[dict]) -> dict:
    """Dịch giả cho import video: `[vi] <câu gốc>`, cấp B1, tiêu đề giữ nguyên."""
    try:
        payload = json.loads(messages[-1]["content"])
    except (ValueError, KeyError, IndexError):
        payload = {}
    sentences = payload.get("sentences") or []
    return {
        "items": [{"i": i, "vi": f"[vi] {text}"} for i, text in enumerate(sentences)],
        "title_vi": payload.get("title") or "",
        "level": "B1",
    }
