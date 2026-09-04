"""L1 — Nạp từ vựng từ CSV (Google Sheets export). Idempotent: upsert theo (headword, pos).

Cột CSV (header, phân tách `,`):
    headword,pos,level,meaning_vi,definition_en,ipa_uk,ipa_us,frequency_rank,
    topics,synonyms,examples,collocations

- `topics`, `synonyms`: nhiều giá trị ngăn bằng `|`  (topics dùng mã code).
- `examples`, `collocations`: nhiều mục ngăn bằng `;;`, mỗi mục là `en|vi`.
- Chạy lại: cập nhật từ đã có, thay mới ví dụ/collocation (không nhân đôi).
"""

import csv

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.content.models import (
    Collocation,
    Level,
    Topic,
    Vocabulary,
    VocabularyExample,
)


def _pairs(raw: str) -> list[tuple[str, str]]:
    out = []
    for item in (raw or "").split(";;"):
        item = item.strip()
        if not item:
            continue
        en, _, vi = item.partition("|")
        out.append((en.strip(), vi.strip()))
    return out


def _multi(raw: str) -> list[str]:
    return [x.strip() for x in (raw or "").split("|") if x.strip()]


class Command(BaseCommand):
    help = "Nạp từ vựng từ file CSV (idempotent theo headword+pos)."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--dry-run", action="store_true", help="Chỉ kiểm, không ghi DB.")

    def handle(self, *args, **opts):
        path = opts["csv_path"]
        dry = opts["dry_run"]
        try:
            fh = open(path, encoding="utf-8-sig", newline="")
        except OSError as e:
            raise CommandError(f"Không mở được file: {e}") from e

        created = updated = skipped = 0
        topic_cache = {t.code: t for t in Topic.objects.all()}
        level_codes = set(Level.objects.values_list("code", flat=True))

        with fh, transaction.atomic():
            reader = csv.DictReader(fh)
            for i, row in enumerate(reader, start=2):  # dòng 1 là header
                headword = (row.get("headword") or "").strip()
                pos = (row.get("pos") or "").strip()
                level = (row.get("level") or "").strip().upper()
                meaning_vi = (row.get("meaning_vi") or "").strip()
                if not (headword and pos and level and meaning_vi):
                    self.stderr.write(f"Bỏ dòng {i}: thiếu trường bắt buộc")
                    skipped += 1
                    continue
                if level not in level_codes:
                    self.stderr.write(f"Bỏ dòng {i}: cấp '{level}' chưa tồn tại")
                    skipped += 1
                    continue

                freq = (row.get("frequency_rank") or "").strip()
                defaults = {
                    "level_id": level,
                    "meaning_vi": meaning_vi,
                    "definition_en": (row.get("definition_en") or "").strip(),
                    "ipa_uk": (row.get("ipa_uk") or "").strip(),
                    "ipa_us": (row.get("ipa_us") or "").strip(),
                    "frequency_rank": int(freq) if freq.isdigit() else None,
                    "synonyms": _multi(row.get("synonyms", "")),
                }
                vocab, was_created = Vocabulary.objects.update_or_create(
                    headword=headword, pos=pos, defaults=defaults
                )
                created += was_created
                updated += not was_created

                vocab.topics.set(
                    [topic_cache[c] for c in _multi(row.get("topics", "")) if c in topic_cache]
                )
                vocab.examples.all().delete()
                VocabularyExample.objects.bulk_create(
                    VocabularyExample(vocabulary=vocab, order=k, text_en=en, text_vi=vi)
                    for k, (en, vi) in enumerate(_pairs(row.get("examples", "")))
                )
                vocab.collocations.all().delete()
                Collocation.objects.bulk_create(
                    Collocation(vocabulary=vocab, text_en=en, meaning_vi=vi)
                    for en, vi in _pairs(row.get("collocations", ""))
                )

            if dry:
                transaction.set_rollback(True)

        tag = "[DRY-RUN] " if dry else ""
        self.stdout.write(
            self.style.SUCCESS(f"{tag}Xong: {created} mới, {updated} cập nhật, {skipped} bỏ qua.")
        )
