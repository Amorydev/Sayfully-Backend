"""Ghi đường dẫn audio Kokoro (crawl/audio/audio_map_skills.csv, sinh từ Data/REVIEW_skills.xlsx) vào các bảng kỹ năng.
  python manage.py import_skills_audio --dry-run       # đếm, không ghi
  python manage.py import_skills_audio                 # ../crawl cạnh Backend/
Khớp theo ref trong CSV: nói/nghe "A1-01#3" → (level, order) của deck/chủ đề + thứ tự câu; ngữ pháp "<source_ref>#<n>";
từ "word:<slug>" → Vocabulary theo slug(headword) (cũng dùng cho WordRoot.samples); drill IPA "ipa#<n>" → IPASound theo symbol.
Chỉ ghi ô có file (done_us/done_uk); không đụng bảng lộ trình (DialogueLine, ReadingSentence, VocabularyExample).
"""

import re
import unicodedata
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.content import models as m
from apps.content.management.commands.import_path import read_csv


def slug(s: str) -> str:
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9.\-]+", "_", s.lower()).strip("_")


class Command(BaseCommand):
    help = "Ghi audio_us_path/audio_uk_path từ crawl/audio/audio_map_skills.csv vào nói, nghe, ngữ pháp, từ vựng, gốc từ, IPA."

    def add_arguments(self, parser):
        parser.add_argument(
            "--crawl-dir", default=str(Path(__file__).resolve().parents[5] / "crawl")
        )
        parser.add_argument("--dry-run", action="store_true", help="Chỉ đếm, không ghi DB.")

    def handle(self, *args, **opts):
        src = Path(opts["crawl_dir"]).resolve() / "audio" / "audio_map_skills.csv"
        if not src.exists():
            raise CommandError(
                f"Không thấy {src} — chạy crawl/audio/gen_tts.py --jobs jobs_skills.jsonl map trước."
            )
        rows = read_csv(src)
        by_ref: dict[tuple[str, str], tuple[str, str]] = {}
        word_key: dict[str, tuple[str, str]] = {}
        for r in rows:
            us = r["key_us"] if r["done_us"] else ""
            uk = r["key_uk"] if r["done_uk"] else ""
            by_ref[(r["target"], r["ref"])] = (us, uk)
            if r["target"] == "vocab":
                word_key[r["key_us"].rsplit("/", 1)[1][:-4]] = (us, uk)
        n = {}

        def apply(obj, us, uk, bucket):
            if not (us or uk):
                return False
            if obj.audio_us_path == us and obj.audio_uk_path == uk:
                return False
            obj.audio_us_path, obj.audio_uk_path = us, uk
            bucket.append(obj)
            return True

        with transaction.atomic():
            upd = []
            for s in m.ShadowingSentence.objects.select_related("deck"):
                apply(
                    s,
                    *by_ref.get(
                        ("speaking", f"{s.deck.level_id}-{s.deck.order:02d}#{s.order}"), ("", "")
                    ),
                    upd,
                )
            m.ShadowingSentence.objects.bulk_update(
                upd, ["audio_us_path", "audio_uk_path"], batch_size=500
            )
            n["nói"] = (len(upd), m.ShadowingSentence.objects.count())

            upd = []
            for it in m.ListeningItem.objects.select_related("topic"):
                apply(
                    it,
                    *by_ref.get(
                        ("listening", f"{it.topic.level_id}-{it.topic.order:02d}#{it.order}"),
                        ("", ""),
                    ),
                    upd,
                )
            m.ListeningItem.objects.bulk_update(
                upd, ["audio_us_path", "audio_uk_path"], batch_size=500
            )
            n["nghe"] = (len(upd), m.ListeningItem.objects.count())

            upd = []
            for e in m.GrammarExample.objects.select_related("grammar_point"):
                apply(
                    e,
                    *by_ref.get(
                        ("grammar_example", f"{e.grammar_point.source_ref}#{e.order}"), ("", "")
                    ),
                    upd,
                )
            m.GrammarExample.objects.bulk_update(
                upd, ["audio_us_path", "audio_uk_path"], batch_size=500
            )
            n["ngữ pháp"] = (len(upd), m.GrammarExample.objects.count())

            upd, dangling = [], 0
            for v in m.Vocabulary.objects.all():
                hit = word_key.get(slug(v.headword))
                if hit:
                    apply(v, *hit, upd)
                elif v.audio_us_path:
                    dangling += 1
            m.Vocabulary.objects.bulk_update(
                upd, ["audio_us_path", "audio_uk_path"], batch_size=500
            )
            n["từ vựng"] = (len(upd), m.Vocabulary.objects.count())

            k = 0
            for root in m.WordRoot.objects.all():
                changed = False
                for s in root.samples:
                    us, uk = word_key.get(slug(s.get("word", "")), ("", ""))
                    if (us or uk) and (
                        s.get("audio_us_path") != us or s.get("audio_uk_path") != uk
                    ):
                        s["audio_us_path"], s["audio_uk_path"] = us, uk
                        changed = True
                        k += 1
                if changed:
                    root.save(update_fields=["samples"])
            n["gốc từ (từ mẫu)"] = (k, sum(len(r.samples) for r in m.WordRoot.objects.all()))

            upd = []
            drill = {
                r["lesson"].split(":", 1)[1].strip("/"): by_ref[("ipa_drill", r["ref"])]
                for r in rows
                if r["target"] == "ipa_drill"
            }
            for snd in m.IPASound.objects.all():
                apply(snd, *drill.get(snd.symbol, ("", "")), upd)
            m.IPASound.objects.bulk_update(upd, ["audio_us_path", "audio_uk_path"])
            n["IPA (drill)"] = (len(upd), m.IPASound.objects.count())

            if opts["dry_run"]:
                transaction.set_rollback(True)

        for k_, (a, b) in n.items():
            self.stdout.write(f"  {k_:18s} cập nhật {a:6d} / {b}")
        if dangling:
            self.stdout.write(
                self.style.WARNING(
                    f"  từ vựng lộ trình có audio_path cũ nhưng không có trong bộ mới: {dangling} (kiểm tra CDN)"
                )
            )
        self.stdout.write(
            self.style.SUCCESS("(dry-run, đã rollback)" if opts["dry_run"] else "Đã ghi.")
        )
