"""Mục tiêu học (`UserProfile.learning_goal`) ↔ nội dung hợp mục tiêu đó.

Mỗi bộ thẻ, chủ đề video và kịch bản đóng vai mang `learning_goals` (danh sách mã LearningGoal).
Nguồn chính là cột "Mục tiêu phù hợp" trong sheet; ô trống thì suy ra bằng các quy tắc bên dưới,
nên dữ liệu cũ vẫn có gợi ý và người biên tập chỉ cần ghi đè những chỗ quy tắc đoán sai.
"""

import re

from apps.common.models import LearningGoal

GOAL_COLUMN = "Mục tiêu phù hợp"

# Tên mục tiêu app hiển thị (thẻ onboarding, Cài đặt); sheet ghi theo tên này hay nhãn LearningGoal đều được.
_APP_TITLES = {
    "giao tiếp": LearningGoal.DAILY,
    "du học (ielts)": LearningGoal.IELTS,
    "công việc (toeic)": LearningGoal.TOEIC,
    "du lịch": LearningGoal.TRAVEL,
    "xem phim & show": LearningGoal.MEDIA,
    "cho con": LearningGoal.KIDS,
}


def parse_goals(text: str | None) -> list[str]:
    """'ielts, Du lịch' → ['ielts', 'travel']: nhận mã, nhãn LearningGoal hoặc tên app hiển thị; bỏ giá trị lạ."""
    by_label = {str(label).lower(): value for value, label in LearningGoal.choices} | _APP_TITLES
    out: list[str] = []
    for part in re.split(r"[,;/|\n]", text or ""):
        key = part.strip().lower()
        goal = key if key in LearningGoal.values else by_label.get(key)
        if goal and goal not in out:
            out.append(goal)
    return out


def deck_goals(code: str) -> list[str]:
    """Bộ thẻ theo mã bộ (slug trong "Từ vựng (Danh mục)")."""
    code = code.lower()
    if "ielts" in code:
        return [LearningGoal.IELTS]
    if "toeic" in code:
        return [LearningGoal.TOEIC]
    if code in ("conversation", "common-1000"):
        return [LearningGoal.DAILY, LearningGoal.TRAVEL, LearningGoal.MEDIA, LearningGoal.KIDS]
    if code == "oxford-3000-a1":
        return [LearningGoal.KIDS]
    return []


# slug chủ đề video (cột "Slug chủ đề") → mục tiêu; tên chủ đề dùng khi chưa có slug.
_VIDEO_BY_SLUG = {
    "movies-animation": [LearningGoal.MEDIA, LearningGoal.KIDS],
    "daily-conversation": [LearningGoal.DAILY, LearningGoal.TRAVEL, LearningGoal.KIDS],
    "culture-lifestyle": [LearningGoal.TRAVEL],
    "business-workplace": [LearningGoal.TOEIC],
    "ted-critical-thinking": [LearningGoal.IELTS],
    "speeches-leadership": [LearningGoal.IELTS],
}
_VIDEO_BY_NAME = {
    "điện ảnh": "movies-animation",
    "giao tiếp": "daily-conversation",
    "văn hoá": "culture-lifestyle",
    "văn hóa": "culture-lifestyle",
    "công sở": "business-workplace",
    "tư duy": "ted-critical-thinking",
    "diễn thuyết": "speeches-leadership",
}


def video_category_goals(slug: str, name: str = "") -> list[str]:
    if not slug:
        lowered = name.lower()
        slug = next((s for key, s in _VIDEO_BY_NAME.items() if key in lowered), "")
    return list(_VIDEO_BY_SLUG.get(slug, []))


def scenario_goals(scene: str, topic: str) -> list[str]:
    """Kịch bản đóng vai theo bối cảnh (`scene`) hoặc chủ đề."""
    if scene in ("airport", "hotel", "directions") or topic == "Du lịch":
        return [LearningGoal.TRAVEL]
    if scene == "interview" or topic == "Công việc":
        return [LearningGoal.TOEIC]
    if scene in ("cafe", "restaurant", "shopping", "doctor"):
        return [LearningGoal.DAILY, LearningGoal.TRAVEL]
    return [LearningGoal.DAILY]
