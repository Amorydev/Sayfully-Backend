"""Build Parroto-style sentence subtitles from caption files.

The mobile player must never generate learning content while a video is playing.  This
module turns VTT/SRT caption cues into durable, sentence-level rows that contain the
timing, English text, US IPA and Vietnamese translation needed by ``VideoWatchScreen``.
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path

import cmudict
from django.conf import settings
from django.core.management.base import CommandError
from django.db import transaction

from apps.content.models import Video, VideoSubtitle
from apps.content.phonemics import arpabet_to_ipa

_TIMING_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})"
)
_TAG_RE = re.compile(r"<[^>]+>")
_WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_NON_SPEECH_RE = re.compile(r"^\s*(?:\[[^]]+]|\([^)]*(?:music|applause)[^)]*\)|[♪♫]+)\s*$", re.I)


@dataclass(frozen=True)
class CaptionCue:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class SubtitleDraft:
    start_ms: int
    end_ms: int
    text_en: str
    ipa: str = ""
    text_vi: str = ""


def parse_timestamp(value: str) -> int:
    """Parse VTT/SRT timestamps (MM:SS.mmm or HH:MM:SS.mmm) to milliseconds."""
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(f"Timestamp không hợp lệ: {value}")
    sec, millis = seconds.split(".", maxsplit=1)
    return ((int(hours) * 60 + int(minutes)) * 60 + int(sec)) * 1000 + int(millis)


def _clean_caption_text(lines: list[str]) -> str:
    text = " ".join(line.strip() for line in lines if line.strip())
    text = html.unescape(_TAG_RE.sub("", text))
    # YouTube VTT sometimes repeats whitespace and non-breaking spaces.
    return re.sub(r"\s+", " ", text).strip()


def parse_caption_text(content: str) -> list[CaptionCue]:
    """Parse either WebVTT or SRT content without pulling in a parser dependency."""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", normalized)
    cues: list[CaptionCue] = []
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if _TIMING_RE.search(line)), None)
        if timing_index is None:
            continue
        match = _TIMING_RE.search(lines[timing_index])
        if match is None:  # pragma: no cover - guarded by the search above
            continue
        text = _clean_caption_text(lines[timing_index + 1 :])
        if not text or _NON_SPEECH_RE.match(text):
            continue
        start_ms = parse_timestamp(match.group("start"))
        end_ms = parse_timestamp(match.group("end"))
        if end_ms <= start_ms:
            raise ValueError(f"Cue có thời gian kết thúc không hợp lệ: {block!r}")
        cues.append(CaptionCue(start_ms=start_ms, end_ms=end_ms, text=text))
    return sorted(cues, key=lambda cue: (cue.start_ms, cue.end_ms))


def _split_cue(cue: CaptionCue) -> list[CaptionCue]:
    """Split a cue containing several punctuated sentences and apportion its duration."""
    parts = [part.strip() for part in _SENTENCE_SPLIT_RE.split(cue.text) if part.strip()]
    if len(parts) <= 1:
        return [cue]
    weights = [max(len(_WORD_RE.findall(part)), 1) for part in parts]
    duration = cue.end_ms - cue.start_ms
    total = sum(weights)
    result: list[CaptionCue] = []
    cursor = cue.start_ms
    consumed = 0
    for index, (part, weight) in enumerate(zip(parts, weights, strict=True)):
        consumed += weight
        end = cue.end_ms if index == len(parts) - 1 else cue.start_ms + duration * consumed // total
        result.append(CaptionCue(cursor, end, part))
        cursor = end
    return result


def segment_cues(
    cues: list[CaptionCue],
    *,
    max_gap_ms: int = 900,
    max_sentence_ms: int = 12_000,
    max_words: int = 28,
) -> list[SubtitleDraft]:
    """Merge caption fragments into sentence-sized, seekable subtitle segments."""
    fragments = [fragment for cue in cues for fragment in _split_cue(cue)]
    output: list[SubtitleDraft] = []
    buffered: list[str] = []
    start_ms = end_ms = 0

    def flush() -> None:
        nonlocal buffered, start_ms, end_ms
        text = re.sub(r"\s+", " ", " ".join(buffered)).strip()
        if text:
            output.append(SubtitleDraft(start_ms=start_ms, end_ms=end_ms, text_en=text))
        buffered = []

    for cue in fragments:
        if buffered and cue.start_ms - end_ms > max_gap_ms:
            flush()
        if not buffered:
            start_ms = cue.start_ms
        buffered.append(cue.text)
        end_ms = cue.end_ms
        word_count = len(_WORD_RE.findall(" ".join(buffered)))
        has_sentence_end = bool(re.search(r"[.!?][\"'’)]?$", cue.text))
        if has_sentence_end or end_ms - start_ms >= max_sentence_ms or word_count >= max_words:
            flush()
    flush()
    return output


def sentence_to_ipa(
    text: str,
    pronunciations: dict[str, list[list[str]]] | None = None,
) -> tuple[str, list[str]]:
    """Return deterministic General-American IPA and words missing from CMUdict."""
    dictionary = pronunciations if pronunciations is not None else cmudict.dict()
    ipa_words: list[str] = []
    missing: list[str] = []
    for match in _WORD_RE.finditer(text):
        source = match.group(0)
        key = source.lower().replace("’", "'").replace("-", "")
        variants = dictionary.get(key)
        if not variants:
            missing.append(source)
            continue
        ipa_words.append(arpabet_to_ipa(variants[0]).ipa.strip("/"))
    return (f"/{' '.join(ipa_words)}/" if ipa_words else ""), missing


def enrich_ipa(drafts: list[SubtitleDraft]) -> tuple[list[SubtitleDraft], list[str]]:
    dictionary = cmudict.dict()
    missing: list[str] = []
    enriched: list[SubtitleDraft] = []
    for draft in drafts:
        if draft.ipa:
            enriched.append(draft)
            continue
        ipa, not_found = sentence_to_ipa(draft.text_en, dictionary)
        enriched.append(replace(draft, ipa=ipa))
        missing.extend(not_found)
    return enriched, list(dict.fromkeys(missing))


def translate_texts_to_vi(texts: list[str]) -> list[str]:
    """Translate a batch through Google Cloud Translation Basic (v2)."""
    if not texts:
        return []
    api_key = getattr(settings, "GOOGLE_TRANSLATE_API_KEY", "")
    if not api_key:
        raise CommandError("Thiếu GOOGLE_TRANSLATE_API_KEY để dùng --translate.")
    url = "https://translation.googleapis.com/language/translate/v2?" + urllib.parse.urlencode(
        {"key": api_key}
    )
    translations: list[str] = []
    # Translation Basic accepts at most 128 `q` values per request.
    for offset in range(0, len(texts), 128):
        chunk = texts[offset : offset + 128]
        body = json.dumps(
            {"q": chunk, "source": "en", "target": "vi", "format": "text"}
        ).encode()
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            # Do not include the request URL: it contains the API key.
            raise CommandError(f"Không dịch được transcript: HTTP {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise CommandError("Không kết nối được Google Translation.") from exc
        rows = payload.get("data", {}).get("translations", [])
        translations.extend(
            html.unescape(row.get("translatedText", "")).strip() for row in rows
        )
    if len(translations) != len(texts) or any(not value for value in translations):
        raise CommandError("Google Translation trả về thiếu câu; database chưa được thay đổi.")
    return translations


def translate_missing(drafts: list[SubtitleDraft]) -> list[SubtitleDraft]:
    missing_indexes = [index for index, draft in enumerate(drafts) if not draft.text_vi]
    translations = translate_texts_to_vi([drafts[index].text_en for index in missing_indexes])
    result = list(drafts)
    for index, translation in zip(missing_indexes, translations, strict=True):
        result[index] = replace(result[index], text_vi=translation)
    return result


def load_subtitle_source(path: Path) -> list[SubtitleDraft]:
    """Load curated JSON, or segment raw VTT/SRT captions."""
    content = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        payload = json.loads(content)
        rows = payload.get("subtitles", payload) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("JSON phải là một list hoặc object có trường 'subtitles'.")
        return [
            SubtitleDraft(
                start_ms=int(row["start_ms"]),
                end_ms=int(row["end_ms"]),
                text_en=str(row["text_en"]).strip(),
                ipa=str(row.get("ipa", "")).strip(),
                text_vi=str(row.get("text_vi", "")).strip(),
            )
            for row in rows
        ]
    if path.suffix.lower() not in {".vtt", ".srt"}:
        raise ValueError("Định dạng hỗ trợ: .json, .vtt, .srt")
    return segment_cues(parse_caption_text(content))


def validate_drafts(drafts: list[SubtitleDraft]) -> None:
    if not drafts:
        raise ValueError("Transcript không có câu thoại hợp lệ.")
    previous_end = -1
    for order, draft in enumerate(drafts, start=1):
        if not draft.text_en:
            raise ValueError(f"Câu #{order} thiếu text_en.")
        if draft.start_ms < 0 or draft.end_ms <= draft.start_ms:
            raise ValueError(f"Câu #{order} có timestamp không hợp lệ.")
        if draft.start_ms < previous_end:
            raise ValueError(f"Câu #{order} chồng timestamp với câu trước.")
        previous_end = draft.end_ms


@transaction.atomic
def replace_video_subtitles(video: Video, drafts: list[SubtitleDraft]) -> int:
    """Atomically replace all subtitle rows after validating the complete draft."""
    validate_drafts(drafts)
    video.subtitles.all().delete()
    VideoSubtitle.objects.bulk_create(
        [
            VideoSubtitle(
                video=video,
                order=order,
                start_ms=draft.start_ms,
                end_ms=draft.end_ms,
                text_en=draft.text_en,
                ipa=draft.ipa,
                text_vi=draft.text_vi,
            )
            for order, draft in enumerate(drafts, start=1)
        ]
    )
    return len(drafts)
