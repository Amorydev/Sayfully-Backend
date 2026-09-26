"""Ước lượng thời lượng một bài học từ chính các bước của nó (thay cho con số cố định lúc nạp lộ trình)."""

import math

from apps.content.models import Lesson, LessonStep

# Phút trung bình cho mỗi bước theo loại; hội thoại tính thêm theo số lượt thoại app hiển thị.
_STEP_MINUTES = {
    LessonStep.Kind.INTRO: 0.5,
    LessonStep.Kind.VOCAB: 0.5,
    LessonStep.Kind.GRAMMAR: 2.0,
    LessonStep.Kind.DIALOGUE: 1.0,
    LessonStep.Kind.SPELLING: 0.75,
    LessonStep.Kind.QUIZ: 0.35,
    LessonStep.Kind.WRITING: 2.0,
    LessonStep.Kind.SPEAK: 1.5,
    LessonStep.Kind.PRON: 1.5,
    LessonStep.Kind.LISTEN: 1.0,
}
_MINUTES_PER_DIALOGUE_LINE = 0.25
MIN_LESSON_MINUTES = 3


def estimate_lesson_minutes(lesson: Lesson) -> int:
    total = 0.0
    for step in lesson.steps.select_related("dialogue"):
        total += _STEP_MINUTES.get(step.kind, 1.0)
        if step.kind == LessonStep.Kind.DIALOGUE and step.dialogue_id:
            total += step.dialogue.lesson_lines().count() * _MINUTES_PER_DIALOGUE_LINE
    return max(MIN_LESSON_MINUTES, math.ceil(total))


def recompute_lesson_minutes(lessons=None) -> int:
    """Tính lại `est_minutes` cho các bài (mặc định: tất cả); trả về số bài có thay đổi."""
    changed = []
    for lesson in lessons if lessons is not None else Lesson.objects.all():
        minutes = estimate_lesson_minutes(lesson)
        if lesson.est_minutes != minutes:
            lesson.est_minutes = minutes
            changed.append(lesson)
    Lesson.objects.bulk_update(changed, ["est_minutes"], batch_size=500)
    return len(changed)
