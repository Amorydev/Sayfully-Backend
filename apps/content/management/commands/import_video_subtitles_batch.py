"""Nạp transcript hàng loạt từ crawl/youtube_subs/video_subtitles.jsonl (kit YouTube subs, bước 3).

  python manage.py import_video_subtitles_batch ../crawl/youtube_subs/video_subtitles.jsonl --translate
  python manage.py import_video_subtitles_batch video_subtitles.jsonl --translate --force     # thay cả video đã có transcript
  python manage.py import_video_subtitles_batch video_subtitles.jsonl --ids abc123,def456 --dry-run

Mỗi dòng: {"youtube_id", "source", "punctuated", "n", "sentences": [{"order", "start_ms", "end_ms", "text_en"}]}.
IPA sinh từ CMUdict; dịch bằng Google Translate (GOOGLE_TRANSLATE_API_KEY) hoặc provider AI của app. Mặc định
bỏ qua video đã có transcript và video không có câu (`empty`); từng video là một transaction, lỗi ghi ra và đi tiếp.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.content.models import Video
from apps.content.video_transcript import (
    SubtitleDraft,
    enrich_ipa,
    replace_video_subtitles,
    translate_missing,
    validate_drafts,
)


def _drafts_from_rows(sentences: list[dict]) -> list[SubtitleDraft]:
    """Cue từ phụ đề/Whisper có thể chồng mép vài ms — kẹp lại cho khớp validate_drafts."""
    drafts: list[SubtitleDraft] = []
    previous_end = 0
    for s_ in sentences:
        text_en = str(s_.get("text_en", "")).strip()[:512]
        if not text_en:
            continue
        start = max(int(s_["start_ms"]), previous_end)
        end = max(int(s_["end_ms"]), start + 1)
        drafts.append(
            SubtitleDraft(
                start_ms=start,
                end_ms=end,
                text_en=text_en,
                ipa=str(s_.get("ipa", "")).strip()[:512],
                text_vi=str(s_.get("text_vi", "")).strip()[:512],
            )
        )
        previous_end = end
    return drafts


class Command(BaseCommand):
    help = "Nạp VideoSubtitle cho nhiều video từ video_subtitles.jsonl (IPA + dịch)."

    def add_arguments(self, parser):
        parser.add_argument("source", type=Path)
        parser.add_argument("--translate", action="store_true", help="Dịch câu chưa có text_vi.")
        parser.add_argument("--force", action="store_true", help="Thay transcript của video đã có.")
        parser.add_argument("--ids", default="", help="Chỉ các youtube_id này (phẩy).")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        source: Path = opts["source"]
        if not source.is_file():
            raise CommandError(f"Không tìm thấy file: {source}")
        only = {x.strip() for x in opts["ids"].split(",") if x.strip()}
        rows = [
            json.loads(line)
            for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if only:
            rows = [r for r in rows if r["youtube_id"] in only]
        if opts["limit"]:
            rows = rows[: opts["limit"]]
        videos = {
            v.youtube_id: v
            for v in Video.objects.filter(youtube_id__in=[r["youtube_id"] for r in rows])
        }
        n_ok = n_skip = n_err = n_missing = 0
        for i, row in enumerate(rows, 1):
            yid = row["youtube_id"]
            video = videos.get(yid)
            if video is None:
                n_missing += 1
                self.stderr.write(f"[{i}/{len(rows)}] {yid}: không có trong DB, bỏ qua")
                continue
            sentences = row.get("sentences") or []
            if not sentences:
                n_skip += 1
                continue
            if video.subtitles.exists() and not opts["force"]:
                n_skip += 1
                continue
            drafts = _drafts_from_rows(sentences)
            try:
                drafts, missing_ipa = enrich_ipa(drafts)
                if opts["translate"]:
                    drafts = translate_missing(drafts)
                validate_drafts(drafts)
                if not opts["dry_run"]:
                    with transaction.atomic():
                        replace_video_subtitles(video, drafts)
                n_ok += 1
                untranslated = sum(not d.text_vi for d in drafts)
                self.stdout.write(
                    f"[{i}/{len(rows)}] {yid}: {len(drafts)} câu ({row.get('source', '?')})"
                    + (f" · thiếu dịch {untranslated}" if untranslated else "")
                    + (f" · {len(missing_ipa)} từ không có IPA" if missing_ipa else "")
                )
            except (CommandError, ValueError, KeyError, TypeError) as exc:
                n_err += 1
                self.stderr.write(f"[{i}/{len(rows)}] {yid}: LỖI {exc}")
        self.stdout.write(
            self.style.SUCCESS(
                f"{'[DRY-RUN] ' if opts['dry_run'] else ''}Nạp {n_ok} video · bỏ qua {n_skip} (đã có / không có câu) · "
                f"{n_missing} không có trong DB · {n_err} lỗi"
            )
        )
