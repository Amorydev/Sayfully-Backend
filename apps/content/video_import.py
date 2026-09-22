"""Người dùng Premium dán link YouTube → Sayfully tự tạo video học.

Luồng: :func:`request_import` kiểm quyền/quota, tạo (hoặc tái dùng) ``Video`` theo ``youtube_id``
rồi đẩy :func:`run_import` cho django-q (hoặc chạy ngay khi ``VIDEO_IMPORT_SYNC``).
``run_import`` lấy caption tiếng Anh, gộp thành câu (:mod:`video_transcript`), sinh IPA,
dịch + ước lượng CEFR bằng LLM, ghi phụ đề và đặt ``status=ready``.

Chỉ nhận video CÓ phụ đề tiếng Anh (kể cả tự động) — không tải audio/ASR.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime, time
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone as djtz

from apps.accounts.models import UserProfile
from apps.ai import llm
from apps.common.exceptions import AppError, Forbidden, RateLimited
from apps.content.models import Level, UserVideoLibrary, Video
from apps.content.video_transcript import (
    _NON_SPEECH_RE,
    CaptionCue,
    SubtitleDraft,
    enrich_ipa,
    replace_video_subtitles,
    segment_cues,
    validate_drafts,
)
from apps.learning.services import local_today

logger = logging.getLogger(__name__)

_YT_ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})")
_YT_BARE_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
# Dòng credit của cộng đồng dịch (TED…) và tiếng động — không phải lời thoại.
_CREDIT_RE = re.compile(
    r"^\s*(?:translator|reviewer|transcriber|subtitles?\s+by|captions?\s+by)\s*:", re.I
)
_LLM_BATCH = 40


class VideoImportError(AppError):
    """422 với ``code`` client phân nhánh: invalid_url / no_captions / too_long / not_embeddable."""

    status_code = 422
    code = "video_import_failed"


@dataclass(frozen=True)
class Preview:
    youtube_id: str
    title: str
    channel: str
    duration_sec: int
    has_english_captions: bool
    embeddable: bool

    @property
    def too_long(self) -> bool:
        return self.duration_sec > settings.VIDEO_IMPORT_MAX_SEC

    @property
    def reject_code(self) -> str:
        if not self.embeddable:
            return "not_embeddable"
        if not self.has_english_captions:
            return "no_captions"
        if self.too_long:
            return "too_long"
        return ""


_REJECT_MESSAGES = {
    "invalid_url": "Link YouTube không hợp lệ",
    "not_embeddable": "Video này không cho phép phát trong ứng dụng",
    "no_captions": "Video này không có phụ đề tiếng Anh",
    "too_long": "Video dài quá {minutes} phút",
    "captions_failed": "Không lấy được phụ đề, thử lại sau",
    "translate_failed": "Không dịch được phụ đề, thử lại sau",
}


def reject_message(code: str) -> str:
    minutes = settings.VIDEO_IMPORT_MAX_SEC // 60
    return _REJECT_MESSAGES.get(code, "Không tạo được bài học từ video này").format(minutes=minutes)


# --------------------------------------------------------------- YouTube
def parse_youtube_id(text: str) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    match = _YT_ID_RE.search(text)
    if match:
        return match.group(1)
    return text if _YT_BARE_RE.match(text) else None


def fetch_oembed(youtube_id: str) -> dict | None:
    """Tiêu đề + kênh không cần API key. ``None`` khi video không tồn tại hoặc cấm nhúng (401/403)."""
    try:
        resp = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={youtube_id}", "format": "json"},
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.warning("oembed failed for %s: %s", youtube_id, exc)
        return None
    if resp.status_code != 200:
        return None
    body = resp.json()
    return {"title": body.get("title") or "", "channel": body.get("author_name") or ""}


def fetch_captions(youtube_id: str) -> list[CaptionCue] | None:
    """Caption tiếng Anh (ưu tiên bản người làm, rồi tự động). ``None`` khi không có."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api import _errors as yt_errors

    try:
        fetched = YouTubeTranscriptApi().fetch(youtube_id, languages=["en", "en-US", "en-GB"])
    except yt_errors.YouTubeTranscriptApiException as exc:
        logger.info("no english captions for %s: %s", youtube_id, type(exc).__name__)
        return None
    return snippets_to_cues(fetched) or None


def snippets_to_cues(snippets) -> list[CaptionCue]:
    """Snippet (text/start/duration giây) → cue ms; bỏ dòng credit và tiếng động."""
    cues: list[CaptionCue] = []
    for snippet in snippets:
        text = re.sub(r"\s+", " ", snippet.text.replace("\n", " ")).strip()
        if not text or _NON_SPEECH_RE.match(text) or _CREDIT_RE.match(text):
            continue
        start_ms = int(round(snippet.start * 1000))
        end_ms = int(round((snippet.start + snippet.duration) * 1000))
        if end_ms <= start_ms:
            end_ms = start_ms + 500
        cues.append(CaptionCue(start_ms=start_ms, end_ms=end_ms, text=text))
    return cues


def preview(youtube_id: str, *, cues: list[CaptionCue] | None = None) -> Preview:
    meta = fetch_oembed(youtube_id)
    if meta is None:
        return Preview(youtube_id, "", "", 0, False, False)
    if cues is None:
        cues = fetch_captions(youtube_id)
    duration = cues[-1].end_ms // 1000 if cues else 0
    return Preview(
        youtube_id=youtube_id,
        title=meta["title"],
        channel=meta["channel"],
        duration_sec=duration,
        has_english_captions=bool(cues),
        embeddable=True,
    )


# --------------------------------------------------------------- quota / request
def quota(profile: UserProfile) -> tuple[int, int]:
    """(còn lại, giới hạn) — đếm video thêm hôm nay theo múi giờ người dùng."""
    limit = settings.VIDEO_IMPORT_DAILY_LIMIT
    start = datetime.combine(local_today(profile), time.min, tzinfo=ZoneInfo(profile.timezone))
    used = UserVideoLibrary.objects.filter(user=profile.user, added_at__gte=start).count()
    return max(limit - used, 0), limit


def ensure_can_import(profile: UserProfile) -> None:
    if not settings.VIDEO_IMPORT_ENABLED:
        raise AppError("Tính năng tạm tắt", code="feature_disabled", status_code=503)
    if not profile.is_premium:
        raise Forbidden("Thêm video YouTube dành cho tài khoản Premium", code="premium_required")


def request_import(profile: UserProfile, url: str) -> Video:
    """Tạo/tái dùng ``Video`` và thêm vào thư viện. Video đã ``ready`` thì trả ngay, không tốn quota."""
    ensure_can_import(profile)
    youtube_id = parse_youtube_id(url)
    if youtube_id is None:
        raise VideoImportError(reject_message("invalid_url"), code="invalid_url")

    existing = Video.objects.filter(youtube_id=youtube_id).first()
    if existing is not None and existing.status == Video.Status.READY:
        UserVideoLibrary.objects.get_or_create(user=profile.user, video=existing)
        return existing

    left, _limit = quota(profile)
    if left <= 0:
        raise RateLimited("Bạn đã dùng hết lượt thêm video hôm nay", code="video_quota_exceeded")

    cues = fetch_captions(youtube_id)
    info = preview(youtube_id, cues=cues)
    if info.reject_code:
        raise VideoImportError(reject_message(info.reject_code), code=info.reject_code)

    with transaction.atomic():
        video, _created = Video.objects.update_or_create(
            youtube_id=youtube_id,
            defaults={
                "title_en": info.title[:160],
                "title_vi": info.title[:160],
                "channel": info.channel[:120],
                "duration_sec": info.duration_sec,
                "category": "",
                "is_free": False,
                "source": Video.Source.USER,
                "status": Video.Status.PENDING,
                "error_code": "",
                "created_by": profile.user,
            },
        )
        UserVideoLibrary.objects.get_or_create(user=profile.user, video=video)
    _dispatch(video.id, cues)
    return video


def _dispatch(video_id: int, cues: list[CaptionCue]) -> None:
    if settings.VIDEO_IMPORT_SYNC:
        run_import(video_id, cues=cues)
        return
    from django_q.tasks import async_task

    async_task(
        "apps.content.video_import.run_import", video_id, task_name=f"video-import-{video_id}"
    )


# --------------------------------------------------------------- worker
def run_import(video_id: int, *, cues: list[CaptionCue] | None = None) -> None:
    video = Video.objects.filter(id=video_id).first()
    if video is None or video.status == Video.Status.READY:
        return
    video.status = Video.Status.PROCESSING
    video.save(update_fields=["status"])
    try:
        if cues is None:
            cues = fetch_captions(video.youtube_id)
        if not cues:
            raise VideoImportError(reject_message("no_captions"), code="no_captions")
        drafts = segment_cues(cues)
        drafts, _missing = enrich_ipa(drafts)
        drafts, title_vi, level_code = translate_with_llm(drafts, title=video.title_en)
        validate_drafts(drafts)
        replace_video_subtitles(video, drafts)
        video.title_vi = (title_vi or video.title_en)[:160]
        video.level = Level.objects.filter(code=level_code).first()
        video.duration_sec = video.duration_sec or drafts[-1].end_ms // 1000
        video.status = Video.Status.READY
        video.error_code = ""
        video.save(update_fields=["title_vi", "level", "duration_sec", "status", "error_code"])
    except Exception as exc:  # noqa: BLE001 — trạng thái lỗi phải được ghi lại cho client
        code = getattr(exc, "code", "") if isinstance(exc, AppError) else ""
        if isinstance(exc, llm.AIUpstreamError):
            code = "translate_failed"
        video.status = Video.Status.FAILED
        video.error_code = code or "captions_failed"
        video.save(update_fields=["status", "error_code"])
        logger.warning("video import %s failed: %s", video_id, exc)


_TRANSLATE_SYSTEM = """You are a translator for an English-learning app (task: VIDEO_TRANSLATE).
Input: JSON {"title": str, "sentences": [str, ...]} — English subtitle sentences from one video.
Return ONLY JSON:
{"items": [{"i": <index>, "vi": "<natural Vietnamese translation>"}, ...],
 "title_vi": "<Vietnamese title, max 12 words>",
 "level": "<CEFR of the spoken English: A1|A2|B1|B2|C1|C2>"}
Rules: one item per sentence, same order, keep names and numbers, keep translations concise.
Only fill title_vi and level in the first batch; otherwise return them as empty strings."""


def translate_with_llm(
    drafts: list[SubtitleDraft], *, title: str
) -> tuple[list[SubtitleDraft], str, str]:
    """Dịch theo lô, trả (drafts đã có text_vi, title_vi, cefr). Ném ``AIUpstreamError`` khi lỗi."""
    result = list(drafts)
    title_vi = ""
    level = ""
    for offset in range(0, len(drafts), _LLM_BATCH):
        batch = drafts[offset : offset + _LLM_BATCH]
        payload = {
            "title": title if offset == 0 else "",
            "sentences": [d.text_en for d in batch],
        }
        completion = llm.complete(
            _TRANSLATE_SYSTEM,
            [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            max_tokens=4000,
            use="video",
        )
        try:
            data = json.loads(completion.text)
            items = {int(item["i"]): str(item["vi"]).strip() for item in data["items"]}
        except (ValueError, KeyError, TypeError) as exc:
            raise llm.AIUpstreamError("Phản hồi dịch không hợp lệ") from exc
        for i, draft in enumerate(batch):
            vi = items.get(i, "")
            if not vi:
                raise llm.AIUpstreamError("Thiếu bản dịch cho một số câu")
            result[offset + i] = replace(draft, text_vi=vi[:512])
        if offset == 0:
            title_vi = str(data.get("title_vi") or "").strip()
            level = str(data.get("level") or "").strip().upper()
    if level not in {"A1", "A2", "B1", "B2", "C1", "C2"}:
        level = "B1"
    return result, title_vi, level


# --------------------------------------------------------------- read side
def can_view(profile: UserProfile, video: Video) -> bool:
    if video.source == Video.Source.CURATED:
        return video.level is None or video.level.is_free or profile.is_premium
    return UserVideoLibrary.objects.filter(user=profile.user, video=video).exists()


def library(profile: UserProfile) -> list[Video]:
    return [
        entry.video
        for entry in UserVideoLibrary.objects.filter(user=profile.user)
        .select_related("video", "video__level")
        .order_by("-added_at")
    ]


def remove_from_library(profile: UserProfile, video_id: int) -> bool:
    deleted, _ = UserVideoLibrary.objects.filter(user=profile.user, video_id=video_id).delete()
    return deleted > 0


def added_label(video: Video, profile: UserProfile) -> str:
    entry = UserVideoLibrary.objects.filter(user=profile.user, video=video).first()
    if entry is None:
        return ""
    days = (djtz.now() - entry.added_at).days
    if days <= 0:
        return "Thêm hôm nay"
    if days == 1:
        return "Thêm hôm qua"
    return f"Thêm {days} ngày trước"
