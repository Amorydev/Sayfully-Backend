"""Seed bảng 44 âm IPA (C43) từ `apps.content.ipa_data`. Idempotent: update_or_create theo symbol."""

from django.core.management.base import BaseCommand

from apps.content.ipa_data import ALL_SOUNDS
from apps.content.models import IPASound


def seed_ipa_sounds() -> int:
    for order, item in enumerate(ALL_SOUNDS):
        other, words = item["pair"]
        examples = [{"word": w, "ipa": ipa, "meaning_vi": vi} for w, ipa, vi in item["examples"]]
        IPASound.objects.update_or_create(
            symbol=item["symbol"],
            defaults={
                "kind": item["kind"],
                "group": item["group"],
                "category_vi": item["category_vi"],
                "category_en": item["category_en"],
                "description_vi": item["description_vi"],
                "articulation_vi": item["articulation_vi"],
                "lips_vi": item["lips_vi"],
                "tongue_vi": item["tongue_vi"],
                "tip_vi": item["tip_vi"],
                "sample_words": [e["word"] for e in examples],
                "examples": examples,
                "minimal_pair": {"other": other, "words": words} if other else {},
                "order": order,
            },
        )
    return len(ALL_SOUNDS)


class Command(BaseCommand):
    help = "Seed 44 âm IPA kèm mô tả tiếng Việt."

    def handle(self, *args, **opts):
        n = seed_ipa_sounds()
        self.stdout.write(self.style.SUCCESS(f"Đã seed {n} âm IPA."))
