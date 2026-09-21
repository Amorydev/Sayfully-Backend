"""Import sentence-level subtitles for VideoWatchScreen from JSON, VTT or SRT."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.content.models import Video
from apps.content.video_transcript import (
    enrich_ipa,
    load_subtitle_source,
    replace_video_subtitles,
    translate_missing,
    validate_drafts,
)


class Command(BaseCommand):
    help = "Import transcript video theo câu, sinh IPA và tùy chọn dịch sang tiếng Việt."

    def add_arguments(self, parser):
        parser.add_argument("source", type=Path, help="File .json, .vtt hoặc .srt.")
        selector = parser.add_mutually_exclusive_group(required=True)
        selector.add_argument("--video-id", type=int)
        selector.add_argument("--youtube-id")
        parser.add_argument(
            "--translate",
            action="store_true",
            help="Dịch các câu thiếu text_vi bằng Google Cloud Translation.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Cho phép thay thế transcript hiện có.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Validate nhưng không ghi DB.")

    def handle(self, *args, **options):
        source: Path = options["source"]
        if not source.is_file():
            raise CommandError(f"Không tìm thấy file: {source}")
        lookup = (
            {"id": options["video_id"]}
            if options["video_id"] is not None
            else {"youtube_id": options["youtube_id"]}
        )
        try:
            video = Video.objects.get(**lookup)
        except Video.DoesNotExist as exc:
            raise CommandError("Không tìm thấy video tương ứng.") from exc
        if video.subtitles.exists() and not options["force"]:
            raise CommandError("Video đã có transcript; thêm --force để thay thế an toàn.")

        try:
            drafts = load_subtitle_source(source)
            drafts, missing_ipa = enrich_ipa(drafts)
            if options["translate"]:
                drafts = translate_missing(drafts)
            validate_drafts(drafts)
        except (KeyError, TypeError, ValueError) as exc:
            raise CommandError(f"Transcript không hợp lệ: {exc}") from exc

        untranslated = sum(not draft.text_vi for draft in drafts)
        if options["dry_run"]:
            prefix = "[DRY-RUN] "
        else:
            replace_video_subtitles(video, drafts)
            prefix = ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Đã xử lý {len(drafts)} câu cho video {video.youtube_id}; "
                f"thiếu dịch: {untranslated}."
            )
        )
        if missing_ipa:
            self.stdout.write(
                self.style.WARNING(
                    "Từ chưa có trong CMUdict, cần rà IPA thủ công: "
                    + ", ".join(missing_ipa[:30])
                    + (" …" if len(missing_ipa) > 30 else "")
                )
            )
