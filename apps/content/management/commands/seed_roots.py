"""Seed 40 gốc từ (C40) từ `apps.content.roots_data`. Idempotent: update_or_create theo (kind, text)."""

from django.core.management.base import BaseCommand

from apps.content.models import WordRoot
from apps.content.roots_data import GROUPS, ROOTS


def seed_word_roots() -> int:
    group_index = {name: i for i, (_, name) in enumerate(GROUPS)}
    counters: dict[str, int] = {}
    for item in ROOTS:
        group = item["group"]
        counters[group] = counters.get(group, 0) + 1
        WordRoot.objects.update_or_create(
            kind=item["kind"],
            text=item["text"],
            defaults={
                "meaning_vi": item["meaning_vi"],
                "group_vi": group,
                "group_order": group_index[group],
                "order": counters[group],
                "effect_vi": item["effect_vi"],
                "mnemonic_vi": item["mnemonic_vi"],
                "samples": [
                    {"word": w, "base": b, "meaning_vi": vi, "ipa": ipa}
                    for w, b, vi, ipa in item["samples"]
                ],
            },
        )
    return len(ROOTS)


class Command(BaseCommand):
    help = "Seed 40 gốc từ kèm từ mẫu."

    def handle(self, *args, **opts):
        n = seed_word_roots()
        self.stdout.write(self.style.SUCCESS(f"Đã seed {n} gốc từ."))
