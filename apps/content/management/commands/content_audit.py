"""L4 — Báo cáo bản ghi thiếu IPA / audio / ví dụ. Chỉ đọc, chạy sau mỗi đợt nhập."""

from django.core.management.base import BaseCommand
from django.db.models import Count, F, Q

from apps.content.models import DialogueLine, Lesson, Video, VideoSubtitle, Vocabulary


class Command(BaseCommand):
    help = "Liệt kê nội dung còn thiếu IPA / audio / ví dụ (chỉ đọc)."

    def add_arguments(self, parser):
        parser.add_argument("--level")

    def handle(self, *args, **opts):
        vq = Vocabulary.objects.all()
        if opts["level"]:
            vq = vq.filter(level_id=opts["level"].upper())

        total = vq.count()
        stats = vq.aggregate(
            no_ipa=Count("id", filter=Q(ipa_us="")),
            no_audio_us=Count("id", filter=Q(audio_us_path="")),
            no_audio_uk=Count("id", filter=Q(audio_uk_path="")),
        )
        no_example = vq.annotate(n=Count("examples")).filter(n=0).count()
        dl_no_audio = DialogueLine.objects.filter(audio_path="").count()
        lq = Lesson.objects.all()
        if opts["level"]:
            lq = lq.filter(unit__level_id=opts["level"].upper())
        lesson_no_path_subtitle = lq.filter(path_subtitle_vi="").count()
        video_qs = Video.objects.all()
        subtitle_qs = VideoSubtitle.objects.all()
        if opts["level"]:
            level = opts["level"].upper()
            video_qs = video_qs.filter(level_id=level)
            subtitle_qs = subtitle_qs.filter(video__level_id=level)
        video_no_transcript = video_qs.annotate(n=Count("subtitles")).filter(n=0).count()
        subtitle_no_ipa = subtitle_qs.filter(ipa="").count()
        subtitle_no_translation = subtitle_qs.filter(text_vi="").count()
        subtitle_bad_timing = subtitle_qs.filter(end_ms__lte=F("start_ms")).count()

        self.stdout.write(self.style.MIGRATE_HEADING(f"Kiểm nội dung — {total} từ vựng"))
        rows = [
            ("Thiếu IPA (ipa_us)", stats["no_ipa"]),
            ("Thiếu audio US", stats["no_audio_us"]),
            ("Thiếu audio UK", stats["no_audio_uk"]),
            ("Thiếu ví dụ", no_example),
            ("Câu hội thoại thiếu audio", dl_no_audio),
            ("Lesson thiếu subtitle Unit sheet", lesson_no_path_subtitle),
            ("Video thiếu transcript", video_no_transcript),
            ("Câu video thiếu IPA", subtitle_no_ipa),
            ("Câu video thiếu bản dịch", subtitle_no_translation),
            ("Câu video sai timestamp", subtitle_bad_timing),
        ]
        for label, n in rows:
            style = self.style.SUCCESS if n == 0 else self.style.WARNING
            self.stdout.write(style(f"  {label:32} {n}"))

        clean = all(n == 0 for _, n in rows)
        self.stdout.write(
            self.style.SUCCESS("Sạch — sẵn sàng build bundle.")
            if clean
            else self.style.WARNING(
                "Còn thiếu — chạy gen_ipa / gen_audio / import_video_subtitles hoặc bổ sung Admin."
            )
        )
