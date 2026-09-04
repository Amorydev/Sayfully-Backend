"""L3 — Sinh audio phát âm (TTS) → upload R2 → ghi đường dẫn vào DB.

Idempotent: bỏ qua từ đã có audio (trừ `--force`). Dùng `--limit 50` để nghe thử một
mẻ nhỏ TRƯỚC khi chạy toàn bộ (mốc kiểm 50 mẫu). `--dry-run` không gọi TTS / không upload.

Backend TTS và uploader là hàm cấp module (`synthesize`, `upload_r2`) — test thay bằng
hàm giả; production nối Azure Speech + boto3/R2 qua settings.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.content.models import Vocabulary

_ACCENTS = {"US": "audio_us_path", "UK": "audio_uk_path"}


def synthesize(text: str, accent: str) -> bytes:
    """Gọi Azure Speech. Chưa cấu hình → báo lỗi rõ (không trả audio rác)."""
    key = getattr(settings, "AZURE_SPEECH_KEY", "")
    if not key:
        raise CommandError(
            "Chưa cấu hình TTS: đặt AZURE_SPEECH_KEY và cài azure-cognitiveservices-speech."
        )
    import azure.cognitiveservices.speech as speechsdk  # noqa: PLC0415

    voice = "en-US-JennyNeural" if accent == "US" else "en-GB-SoniaNeural"
    cfg = speechsdk.SpeechConfig(subscription=key, region=settings.AZURE_SPEECH_REGION)
    cfg.speech_synthesis_voice_name = voice
    cfg.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3
    )
    synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
    result = synth.speak_text_async(text).get()
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        raise CommandError(f"TTS lỗi cho '{text}': {result.reason}")
    return result.audio_data


def upload_r2(key: str, data: bytes) -> str:
    import boto3  # noqa: PLC0415

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )
    client.put_object(Bucket=settings.R2_BUCKET, Key=key, Body=data, ContentType="audio/mpeg")
    return key


class Command(BaseCommand):
    help = "Sinh audio TTS US/UK, upload R2, ghi đường dẫn (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--level")
        parser.add_argument("--accent", default="US,UK", help="US, UK hoặc 'US,UK'.")
        parser.add_argument("--limit", type=int, help="Chỉ xử lý N từ (nghe thử mẻ nhỏ).")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        accents = [a.strip().upper() for a in opts["accent"].split(",") if a.strip()]
        bad = [a for a in accents if a not in _ACCENTS]
        if bad:
            raise CommandError(f"Accent không hợp lệ: {bad}. Chỉ US, UK.")

        dry = opts["dry_run"]
        total = 0
        for accent in accents:
            field = _ACCENTS[accent]
            qs = Vocabulary.objects.all()
            if opts["level"]:
                qs = qs.filter(level_id=opts["level"].upper())
            if not opts["force"]:
                qs = qs.filter(**{field: ""})
            qs = qs.order_by("frequency_rank", "headword")
            if opts["limit"]:
                qs = qs[: opts["limit"]]

            n = 0
            for vocab in qs:
                path = f"audio/{accent.lower()}/{vocab.headword.lower()}.mp3"
                if not dry:
                    data = synthesize(vocab.headword, accent)
                    upload_r2(path, data)
                    setattr(vocab, field, path)
                    vocab.save(update_fields=[field])
                n += 1
            total += n
            self.stdout.write(f"{accent}: {n} từ")

        tag = "[DRY-RUN] " if dry else ""
        self.stdout.write(self.style.SUCCESS(f"{tag}Tổng {total} audio."))
