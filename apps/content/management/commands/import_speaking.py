"""Nạp deck luyện nói từ crawl/speaking/speaking_decks.json (60 deck = 60 unit lộ trình × 15 câu viết tay).

  python manage.py import_speaking                    # ../crawl cạnh Backend/
  python manage.py import_speaking --crawl-dir /path/to/crawl --purge   # xoá deck không có trong file (deck demo)

Deck khoá theo (level, order) = (unit.level, unit.order). IPA câu sinh tất định từ CMUdict (`sentence_ipa`),
highlight → `[{"text", "kind": "primary_stress"}]`, audio lấy từ crawl/audio/audio_map.csv theo ref "<deck>#<n>".
"""

import json
from pathlib import Path

import cmudict
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.content import models as m
from apps.content.management.commands.import_path import read_csv
from apps.content.phonemics import sentence_ipa

# Màu thẻ theo thứ tự unit trong level (app dùng làm nền/nhấn khi chưa có ảnh)
PALETTE = ["#4F46E5", "#22C55E", "#FF6B57", "#38BDF8", "#7C3AED", "#F59E0B"]
SECONDS_PER_SENTENCE = 12


class Command(BaseCommand):
    help = "Nạp deck luyện nói (ShadowingDeck/ShadowingSentence) từ crawl/speaking/speaking_decks.json."

    def add_arguments(self, parser):
        parser.add_argument(
            "--crawl-dir", default=str(Path(__file__).resolve().parents[5] / "crawl")
        )
        parser.add_argument(
            "--purge", action="store_true", help="Xoá deck không có trong file (vd deck demo)."
        )

    def handle(self, *args, **opts):
        crawl = Path(opts["crawl_dir"]).resolve()
        src = crawl / "speaking" / "speaking_decks.json"
        if not src.exists():
            raise CommandError(f"Không thấy {src} — chạy crawl/speaking/build_speaking.py trước.")
        data = json.load(open(src, encoding="utf-8"))
        audio: dict[str, tuple[str, str]] = {}
        am = crawl / "audio" / "audio_map.csv"
        if am.exists():
            for r in read_csv(am):
                audio[r["ref"]] = (
                    r["key_us"] if r["done_us"] else "",
                    r["key_uk"] if r["done_uk"] else "",
                )
        cmu = cmudict.dict()
        levels = {lv.code: lv for lv in m.Level.objects.all()}

        with transaction.atomic():
            keep = []
            n_sent = n_audio = 0
            for d in data["decks"]:
                level = levels.get(d["level"])
                if not level:
                    raise CommandError(f"Level {d['level']} chưa có trong DB")
                deck, _ = m.ShadowingDeck.objects.update_or_create(
                    level=level,
                    order=d["order"],
                    defaults={
                        "title_en": d["title_en"][:128],
                        "title_vi": (d.get("title_vi") or "")[:128],
                        "focus_vi": (d.get("focus_vi") or "")[:128],
                        "est_seconds": len(d["sentences"]) * SECONDS_PER_SENTENCE,
                        "color": PALETTE[(d["order"] - 1) % len(PALETTE)],
                        "is_free": level.is_free,
                    },
                )
                keep.append(deck.id)
                deck.sentences.all().delete()
                rows = []
                for s_ in d["sentences"]:
                    us, uk = audio.get(f"{d['code']}#{s_['order']}", ("", ""))
                    n_audio += bool(us or uk)
                    hl = (s_.get("highlight") or "").strip()
                    rows.append(
                        m.ShadowingSentence(
                            deck=deck,
                            order=s_["order"],
                            text_en=s_["text_en"][:512],
                            ipa=sentence_ipa(s_["text_en"], cmu)[:512],
                            text_vi=(s_.get("text_vi") or "")[:512],
                            speaking_goal_vi=(s_.get("speaking_goal_vi") or "")[:255],
                            highlights=[{"text": hl, "kind": "primary_stress"}] if hl else [],
                            audio_us_path=us,
                            audio_uk_path=uk,
                        )
                    )
                m.ShadowingSentence.objects.bulk_create(rows)
                n_sent += len(rows)
            n_purged = 0
            if opts["purge"]:
                n_purged, _ = m.ShadowingDeck.objects.exclude(id__in=keep).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Nạp {len(keep)} deck · {n_sent} câu · {n_audio} câu có audio"
                + (f" · xoá {n_purged} deck cũ" if opts["purge"] else "")
            )
        )
