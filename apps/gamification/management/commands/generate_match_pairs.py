"""Sinh chặng Ghép cặp từ các bộ từ vựng Oxford (từ đã có cấp CEFR).

  python manage.py generate_match_pairs            # tạo/cập nhật chặng oxford-a1-001…
  python manage.py generate_match_pairs --dry-run  # chỉ đếm

Chặng sinh ra đứng sau các chặng biên tập tay (seed_match_pairs) theo `order`. Chạy lại là upsert
theo `code`: tiến độ người chơi giữ theo chặng, bộ cặp được nạp lại; chặng `oxford-*` không còn
trong kết quả mới bị tắt chứ không xoá, để không mất sao đã đạt.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.content.models import Vocabulary, VocabularyDeckItem
from apps.gamification.match_pairs_pool import CODE_PREFIX, build_stages
from apps.gamification.models import MatchPairsStage, MatchPairsWord

FIRST_ORDER = 100


class Command(BaseCommand):
    help = "Sinh chặng Ghép cặp từ bộ từ vựng Oxford (theo cấp A1 → C1)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, *args, **opts):
        # Đi theo thứ tự thẻ trong các bộ Oxford (xếp theo bài) để một chặng gom từ cùng chủ đề.
        words = (
            VocabularyDeckItem.objects.filter(
                deck__code__startswith="oxford-",
                vocabulary__level__isnull=False,
                vocabulary__in=Vocabulary.objects.game_words(),
            )
            .order_by("deck__code", "order", "id")
            .values_list("vocabulary__headword", "vocabulary__meaning_vi", "vocabulary__level_id")
        )
        stages = build_stages(words)
        per_level: dict[str, int] = {}
        for spec in stages:
            per_level[spec["level"]] = per_level.get(spec["level"], 0) + 1
        summary = ", ".join(f"{level}: {n}" for level, n in per_level.items()) or "0"
        if opts["dry_run"]:
            self.stdout.write(f"Sẽ sinh {len(stages)} chặng ({summary})")
            return

        for index, spec in enumerate(stages):
            stage, _ = MatchPairsStage.objects.update_or_create(
                code=spec["code"],
                defaults={
                    "title_vi": spec["title_vi"],
                    "subtitle_vi": spec["subtitle_vi"],
                    "symbol": spec["symbol"],
                    "level": spec["level"],
                    "order": FIRST_ORDER + index,
                    "is_active": True,
                },
            )
            stage.pairs.all().delete()
            MatchPairsWord.objects.bulk_create(
                MatchPairsWord(stage=stage, order=i, english=english, vietnamese=vietnamese)
                for i, (english, vietnamese) in enumerate(spec["pairs"])
            )
        retired = (
            MatchPairsStage.objects.filter(code__startswith=CODE_PREFIX, is_active=True)
            .exclude(code__in=[s["code"] for s in stages])
            .update(is_active=False)
        )
        self.stdout.write(
            self.style.SUCCESS(f"Đã sinh {len(stages)} chặng Ghép cặp ({summary}); tắt {retired} chặng cũ")
        )
