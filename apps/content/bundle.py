"""Đóng gói nội dung 1 cấp thành dict JSON tĩnh cho app tải offline (G5).

Accent-agnostic: mang cả ipa_uk/ipa_us và audio 2 giọng để client chọn tại chỗ.
Dùng lại cấu trúc bước G2 (LessonStep đa hình).
"""

from django.conf import settings

from .models import Level


def _media(path: str) -> str | None:
    return f"{settings.R2_PUBLIC_BASE.rstrip('/')}/{path}" if path else None


def _vocab(v) -> dict:
    return {
        "id": v.id,
        "headword": v.headword,
        "pos": v.pos,
        "level": v.level_id,
        "ipa_uk": v.ipa_uk,
        "ipa_us": v.ipa_us,
        "syllables": v.syllables,
        "ipa_syllables": v.ipa_syllables,
        "primary_stress": v.primary_stress,
        "secondary_stress": v.secondary_stress,
        "meaning_vi": v.meaning_vi,
        "audio_uk_url": _media(v.audio_uk_path),
        "audio_us_url": _media(v.audio_us_path),
        "examples": [
            {"text_en": e.text_en, "text_vi": e.text_vi, "audio_url": _media(e.audio_path)}
            for e in v.examples.all()
        ],
        "collocations": [
            {"text_en": c.text_en, "meaning_vi": c.meaning_vi} for c in v.collocations.all()
        ],
    }


def _grammar(g) -> dict:
    return {
        "id": g.id,
        "title_vi": g.title_vi,
        "title_en": g.title_en,
        "formula": g.formula,
        "explanation_vi": g.explanation_vi,
        "common_mistake_vi": g.common_mistake_vi,
        "conjugation": g.conjugation,
        "examples": [
            {"text_en": e.text_en, "ipa": e.ipa, "text_vi": e.text_vi, "audio_url": _media(e.audio_path)}
            for e in g.examples.all()
        ],
    }


def _dialogue(d) -> dict:
    return {
        "id": d.id,
        "title_en": d.title_en,
        "title_vi": d.title_vi,
        "context_vi": d.context_vi,
        "lines": [
            {
                "order": ln.order,
                "speaker": ln.speaker,
                "is_native": ln.is_native,
                "text_en": ln.text_en,
                "ipa": ln.ipa,
                "text_vi": ln.text_vi,
                "audio_url": _media(ln.audio_path),
            }
            for ln in d.lines.all()
        ],
    }


def _step(step) -> dict:
    out = {"order": step.order, "kind": step.kind}
    if step.kind == "vocab" and step.vocabulary_id:
        out["vocab"] = _vocab(step.vocabulary)
    elif step.kind == "grammar" and step.grammar_point_id:
        out["grammar"] = _grammar(step.grammar_point)
    elif step.kind == "dialogue" and step.dialogue_id:
        out["dialogue"] = _dialogue(step.dialogue)
    elif step.kind in ("intro", "spelling", "quiz"):
        out[step.kind] = step.payload or {}
    return out


def build_level_bundle(level: Level) -> dict:
    units = []
    for unit in level.units.order_by("order"):
        lessons = []
        for lesson in unit.lessons.order_by("order"):
            lessons.append(
                {
                    "code": lesson.code,
                    "order": lesson.order,
                    "title_vi": lesson.title_vi,
                    "title_en": lesson.title_en,
                    "est_minutes": lesson.est_minutes,
                    "xp_reward": lesson.xp_reward,
                    "steps": [
                        _step(st)
                        for st in lesson.steps.select_related(
                            "vocabulary", "grammar_point", "dialogue"
                        ).order_by("order")
                    ],
                }
            )
        units.append(
            {
                "id": unit.id,
                "order": unit.order,
                "code": unit.code,
                "title_vi": unit.title_vi,
                "title_en": unit.title_en,
                "reward": unit.reward or {},
                "lessons": lessons,
            }
        )
    return {"level": level.code, "units": units}
