"""Tiến độ luyện video theo câu (Luyện đọc / Chép chính tả).

`record_result` được gọi từ `POST /learn/practice` khi `ref_id` có dạng ``video:<id>:<order>``;
`summaries` / `detail` cung cấp dữ liệu cho sheet "Chọn cách học" và màn xem video.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from django.db.models import Count, Max

from .models import VideoPracticeResult

_REF_RE = re.compile(r"^video:(\d+):(\d+)$")
MODES = ("shadowing", "dictation")


def parse_ref(ref_id: str) -> tuple[int, int] | None:
    """``video:7:12`` → (7, 12); None nếu không phải ref của video."""
    m = _REF_RE.match(ref_id or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def record_result(user, video_id: int, mode: str, order: int, percent: int) -> None:
    """Giữ điểm tốt nhất, đếm số lần thử. Bỏ qua nếu mode/video không hợp lệ."""
    if mode not in MODES:
        return
    from apps.content.models import Video

    if not Video.objects.filter(id=video_id).exists():
        return
    row, created = VideoPracticeResult.objects.get_or_create(
        user=user, video_id=video_id, mode=mode, order=order, defaults={"percent": percent}
    )
    if not created:
        row.percent = max(row.percent, percent)
        row.attempts += 1
        row.save(update_fields=["percent", "attempts", "updated_at"])


@dataclass
class PracticeSummary:
    shadowing_done: int = 0
    dictation_done: int = 0
    last_mode: str | None = None
    last_practiced_at: datetime | None = None


def summaries(user, video_ids: list[int]) -> dict[int, PracticeSummary]:
    """Số câu đã luyện theo mode + mode dùng gần nhất, cho từng video (một query)."""
    out: dict[int, PracticeSummary] = defaultdict(PracticeSummary)
    if not video_ids:
        return out
    rows = (
        VideoPracticeResult.objects.filter(user=user, video_id__in=video_ids)
        .values("video_id", "mode")
        .annotate(n=Count("id"), last=Max("updated_at"))
    )
    latest: dict[int, tuple] = {}
    for r in rows:
        summary = out[r["video_id"]]
        if r["mode"] == "shadowing":
            summary.shadowing_done = r["n"]
        else:
            summary.dictation_done = r["n"]
        if r["video_id"] not in latest or r["last"] > latest[r["video_id"]][0]:
            latest[r["video_id"]] = (r["last"], r["mode"])
    for vid, (at, mode) in latest.items():
        out[vid].last_mode = mode
        out[vid].last_practiced_at = at
    return out


@dataclass
class PracticeDetail:
    summary: PracticeSummary = field(default_factory=PracticeSummary)
    shadowing: dict[int, int] = field(default_factory=dict)  # order → percent
    dictation: dict[int, int] = field(default_factory=dict)


def detail(user, video_id: int) -> PracticeDetail:
    """Kết quả từng câu để mở lại video thấy câu đã chấm."""
    result = PracticeDetail(summary=summaries(user, [video_id])[video_id])
    for row in VideoPracticeResult.objects.filter(user=user, video_id=video_id).only(
        "mode", "order", "percent"
    ):
        (result.shadowing if row.mode == "shadowing" else result.dictation)[row.order] = row.percent
    return result
