"""Nạp bài đọc hiểu từ crawl/reading/reading_passages.json (bài đọc viết lại, 151 bài A2–C1).

  python manage.py import_reading                    # ../crawl cạnh Backend/
  python manage.py import_reading --crawl-dir /path/to/crawl --purge   # xoá bài không có trong file (demo)

Bài khoá theo (level, order) như trong file. IPA câu sinh từ CMUdict (`sentence_ipa`), audio theo
crawl/audio/audio_map.csv với ref "<mã bài>#<n>" (target `reading` của gen_tts), keywords = Vocabulary theo
source_ref (id EVP), topic theo Topic.code.
"""

import json
from pathlib import Path

import cmudict
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.content import models as m
from apps.content.management.commands.import_path import read_csv
from apps.content.phonemics import sentence_ipa


class Command(BaseCommand):
    help = "Nạp bài đọc hiểu (Reading/ReadingSentence/ReadingQuestion) từ crawl/reading/reading_passages.json."

    def add_arguments(self, parser):
        parser.add_argument(
            "--crawl-dir", default=str(Path(__file__).resolve().parents[5] / "crawl")
        )
        parser.add_argument(
            "--purge", action="store_true", help="Xoá bài đọc không có trong file (vd demo)."
        )

    def handle(self, *args, **opts):
        crawl = Path(opts["crawl_dir"]).resolve()
        src = crawl / "reading" / "reading_passages.json"
        if not src.exists():
            raise CommandError(f"Không thấy {src} — chạy crawl/reading/build_reading.py trước.")
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
        topics = {t.code: t for t in m.Topic.objects.all()}
        vocab_by_ref = {
            v.source_ref: v
            for v in m.Vocabulary.objects.exclude(source_ref="").only("id", "source_ref")
        }

        with transaction.atomic():
            keep = []
            n_sent = n_q = n_audio = n_kw = 0
            for p in data["passages"]:
                level = levels.get(p["level"])
                if not level:
                    raise CommandError(f"Level {p['level']} chưa có trong DB")
                topic = topics.get(p.get("topic") or "")
                if p.get("topic") and not topic:
                    self.stderr.write(
                        f"  {p['code']}: topic '{p['topic']}' không có trong DB, bỏ qua"
                    )
                reading, _ = m.Reading.objects.update_or_create(
                    level=level,
                    order=p["order"],
                    defaults={
                        "title_en": p["title_en"][:128],
                        "title_vi": p["title_vi"][:128],
                        "topic": topic,
                        "est_minutes": p.get("est_minutes") or 2,
                    },
                )
                keep.append(reading.id)
                kws = [vocab_by_ref[k] for k in p.get("keywords", []) if k in vocab_by_ref]
                reading.keywords.set(kws)
                n_kw += len(kws)
                reading.sentences.all().delete()
                rows = []
                for i, s_ in enumerate(p["sentences"], 1):
                    us, uk = audio.get(f"{p['code']}#{i}", ("", ""))
                    n_audio += bool(us or uk)
                    rows.append(
                        m.ReadingSentence(
                            reading=reading,
                            order=i,
                            text_en=s_["text_en"][:512],
                            text_vi=s_["text_vi"][:512],
                            ipa=sentence_ipa(s_["text_en"], cmu)[:512],
                            audio_us_path=us,
                            audio_uk_path=uk,
                        )
                    )
                m.ReadingSentence.objects.bulk_create(rows)
                n_sent += len(rows)
                reading.questions.all().delete()
                m.ReadingQuestion.objects.bulk_create(
                    [
                        m.ReadingQuestion(
                            reading=reading,
                            order=i,
                            question_en=q["question_en"][:512],
                            options=q["options"],
                            answer_index=q["answer_index"],
                            explanation_vi=q["explanation_vi"][:512],
                        )
                        for i, q in enumerate(p["questions"], 1)
                    ]
                )
                n_q += len(p["questions"])
            n_purged = 0
            if opts["purge"]:
                n_purged, _ = m.Reading.objects.exclude(id__in=keep).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Nạp {len(keep)} bài · {n_sent} câu · {n_q} câu hỏi · {n_kw} từ khoá · {n_audio} câu có audio"
                + (f" · xoá {n_purged} bài cũ" if opts["purge"] else "")
            )
        )
