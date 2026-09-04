"""L2 — Sinh IPA + âm tiết + trọng âm từ CMUdict. KHÔNG dùng LLM (nó bịa IPA).

`ipa_us` (General American), `ipa_syllables`, `primary_stress`, `secondary_stress` lấy từ
CMUdict; `syllables` (chính tả) từ pyphen. `ipa_uk` không đụng tới — CMUdict là US;
UK nhập tay cho từ trọng yếu.

Idempotent: chỉ xử lý từ chưa có `ipa_us`, trừ khi `--force`.
"""

import cmudict
import pyphen
from django.core.management.base import BaseCommand

from apps.content.models import Vocabulary
from apps.content.phonemics import arpabet_to_ipa


class Command(BaseCommand):
    help = "Sinh IPA/âm tiết/trọng âm từ CMUdict (US)."

    def add_arguments(self, parser):
        parser.add_argument("--level", help="Chỉ xử lý một cấp, ví dụ A1.")
        parser.add_argument("--force", action="store_true", help="Ghi đè cả từ đã có IPA.")

    def handle(self, *args, **opts):
        cmu = cmudict.dict()
        hyphen = pyphen.Pyphen(lang="en_US")

        qs = Vocabulary.objects.all()
        if opts["level"]:
            qs = qs.filter(level_id=opts["level"].upper())
        if not opts["force"]:
            qs = qs.filter(ipa_us="")

        done = missing = 0
        misses: list[str] = []
        for vocab in qs.iterator():
            key = vocab.headword.lower()
            pron = cmu.get(key)
            if not pron:
                missing += 1
                misses.append(vocab.headword)
                continue
            result = arpabet_to_ipa(pron[0])
            vocab.ipa_us = result.ipa
            vocab.ipa_syllables = result.ipa_syllables
            vocab.primary_stress = result.primary_stress
            vocab.secondary_stress = result.secondary_stress
            vocab.syllables = hyphen.inserted(vocab.headword).split("-")
            vocab.save(
                update_fields=[
                    "ipa_us",
                    "ipa_syllables",
                    "primary_stress",
                    "secondary_stress",
                    "syllables",
                ]
            )
            done += 1

        self.stdout.write(self.style.SUCCESS(f"Sinh IPA cho {done} từ."))
        if misses:
            self.stdout.write(
                self.style.WARNING(
                    f"{missing} từ không có trong CMUdict (nhập IPA tay): "
                    + ", ".join(misses[:20])
                    + (" …" if missing > 20 else "")
                )
            )
