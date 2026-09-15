"""Seed điểm ngữ pháp C42 từ `apps.content.grammar_data`. Idempotent theo (level, order)."""

from django.core.management.base import BaseCommand

from apps.content.grammar_data import POINTS
from apps.content.models import GrammarExample, GrammarExercise, GrammarPoint, Level


def seed_grammar_points() -> int:
    levels = {lv.code: lv for lv in Level.objects.all()}
    n = 0
    for item in POINTS:
        level = levels.get(item["level"])
        if level is None:
            continue
        hint, wrong, right = item["mistake"]
        gp, _ = GrammarPoint.objects.update_or_create(
            level=level,
            order=item["order"],
            defaults={
                "category": item["category"],
                "title_vi": item["title_vi"],
                "title_en": item["title_en"],
                "subtitle_vi": item["subtitle_vi"],
                "form_vi": item["form_vi"],
                "formula": item["formula"],
                "formula_parts": [{"token": t, "label_vi": lbl} for t, lbl in item["parts"]],
                "note_vi": item["note_vi"],
                "explanation_vi": item["explanation_vi"],
                "common_mistake_vi": hint,
                "mistake_wrong": wrong,
                "mistake_right": right,
                "conjugation": [{"subject": s, "form": f} for s, f in item["conjugation"]],
            },
        )
        gp.examples.all().delete()
        for i, (en, vi) in enumerate(item["examples"]):
            GrammarExample.objects.create(grammar_point=gp, order=i, text_en=en, text_vi=vi)
        gp.exercises.all().delete()
        for i, (en, vi, options, answer, why) in enumerate(item["exercises"]):
            GrammarExercise.objects.create(
                grammar_point=gp,
                order=i,
                prompt_en=en,
                prompt_vi=vi,
                options=list(options),
                answer_index=answer,
                explanation_vi=why,
            )
        n += 1
    return n


class Command(BaseCommand):
    help = "Seed điểm ngữ pháp A1/A2 kèm ví dụ và câu thực hành."

    def handle(self, *args, **opts):
        n = seed_grammar_points()
        self.stdout.write(self.style.SUCCESS(f"Đã seed {n} điểm ngữ pháp."))
