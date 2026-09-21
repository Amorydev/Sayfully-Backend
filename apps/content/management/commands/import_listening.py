"""Nạp chủ đề luyện nghe từ crawl/listening/listening_topics.json (60 chủ đề = 60 unit lộ trình × ≤12 câu).

  python manage.py import_listening                    # ../crawl cạnh Backend/
  python manage.py import_listening --crawl-dir /path/to/crawl --purge   # xoá chủ đề không có trong file (demo)

Chủ đề khoá theo (level, order) = (unit.level, unit.order). Audio lấy từ crawl/audio/audio_map.csv theo ref lượt thoại
"<dialogue>#<n>" (dùng chung mp3 với bước hội thoại).
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.content import models as m
from apps.content.management.commands.import_path import read_csv

PALETTE = ["#4F46E5", "#22C55E", "#FF6B57", "#38BDF8", "#7C3AED", "#F59E0B"]
SECONDS_PER_ITEM = 10


class Command(BaseCommand):
    help = "Nạp chủ đề luyện nghe (ListeningTopic/ListeningItem) từ crawl/listening/listening_topics.json."

    def add_arguments(self, parser):
        parser.add_argument(
            "--crawl-dir", default=str(Path(__file__).resolve().parents[5] / "crawl")
        )
        parser.add_argument(
            "--purge", action="store_true", help="Xoá chủ đề không có trong file (vd demo)."
        )

    def handle(self, *args, **opts):
        crawl = Path(opts["crawl_dir"]).resolve()
        src = crawl / "listening" / "listening_topics.json"
        if not src.exists():
            raise CommandError(f"Không thấy {src} — chạy crawl/listening/build_listening.py trước.")
        data = json.load(open(src, encoding="utf-8"))
        audio: dict[str, tuple[str, str]] = {}
        am = crawl / "audio" / "audio_map.csv"
        if am.exists():
            for r in read_csv(am):
                audio[r["ref"]] = (
                    r["key_us"] if r["done_us"] else "",
                    r["key_uk"] if r["done_uk"] else "",
                )
        levels = {lv.code: lv for lv in m.Level.objects.all()}

        with transaction.atomic():
            keep = []
            n_item = n_audio = 0
            for t in data["topics"]:
                level = levels.get(t["level"])
                if not level:
                    raise CommandError(f"Level {t['level']} chưa có trong DB")
                topic, _ = m.ListeningTopic.objects.update_or_create(
                    level=level,
                    order=t["order"],
                    defaults={
                        "title_vi": t["title_vi"][:128],
                        "est_seconds": len(t["items"]) * SECONDS_PER_ITEM,
                        "color": PALETTE[(t["order"] - 1) % len(PALETTE)],
                        "is_free": level.is_free,
                    },
                )
                keep.append(topic.id)
                topic.items.all().delete()
                rows = []
                for it in t["items"]:
                    us, uk = audio.get(it["ref"], ("", ""))
                    n_audio += bool(us or uk)
                    rows.append(
                        m.ListeningItem(
                            topic=topic,
                            order=it["order"],
                            text_en=it["text_en"][:512],
                            text_vi=(it.get("text_vi") or "")[:512],
                            blank_index=it["blank_index"],
                            options=it["options"],
                            answer_index=it["answer_index"],
                            audio_us_path=us,
                            audio_uk_path=uk,
                        )
                    )
                m.ListeningItem.objects.bulk_create(rows)
                n_item += len(rows)
            n_purged = 0
            if opts["purge"]:
                n_purged, _ = m.ListeningTopic.objects.exclude(id__in=keep).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Nạp {len(keep)} chủ đề · {n_item} câu · {n_audio} câu có audio"
                + (f" · xoá {n_purged} chủ đề cũ" if opts["purge"] else "")
            )
        )
