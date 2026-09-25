"""Cắt bộ từ vựng Oxford thành các chặng Ghép cặp.

Một ván chỉ thắng được khi mọi thẻ tiếng Anh và mọi nghĩa tiếng Việt trong chặng đều khác nhau,
và nhãn phải đủ ngắn để in lên thẻ. Nghĩa trong kho từ vựng thường gộp nhiều ý ("đồng ý, tán
thành; thỏa thuận"), nên chỉ lấy ý đầu; từ nào trùng nghĩa với từ đã có trong chặng thì dời sang
chặng sau thay vì bỏ.
"""

import re
from collections.abc import Iterable

CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
PAIRS_PER_STAGE = 12
MAX_ENGLISH = 14
MAX_VIETNAMESE = 22
LEVEL_SYMBOLS = {"A1": "✦", "A2": "◈", "B1": "◆", "B2": "★", "C1": "❖", "C2": "✺"}
CODE_PREFIX = "oxford-"


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def short_meaning(meaning: str) -> str:
    """Ý đầu tiên của nghĩa, bỏ phần trong ngoặc; giữ cụm 'a, b' nếu còn đủ ngắn để in lên thẻ."""
    first = re.sub(r"\([^)]*\)", "", meaning.split(";")[0]).strip(" ,.")
    first = re.sub(r"\s+", " ", first)
    if len(first) > MAX_VIETNAMESE:
        first = first.split(",")[0].strip()
    return _capitalize(first) if 0 < len(first) <= MAX_VIETNAMESE else ""


def build_stages(words: Iterable[tuple[str, str, str]]) -> list[dict]:
    """
    [(headword, meaning_vi, level)] theo thứ tự ưu tiên → danh sách chặng đủ [PAIRS_PER_STAGE] cặp,
    đi lần lượt A1 → C2. Phần lẻ cuối mỗi cấp (chưa đủ một chặng) bị bỏ vì ván không chơi được.
    """
    by_level: dict[str, list[tuple[str, str]]] = {level: [] for level in CEFR_LEVELS}
    seen_english: set[str] = set()
    for headword, meaning, level in words:
        english = headword.strip()
        vietnamese = short_meaning(meaning)
        if level not in by_level or not vietnamese or len(english) > MAX_ENGLISH:
            continue
        if english.lower() in seen_english or english.lower() == vietnamese.lower():
            continue
        seen_english.add(english.lower())
        by_level[level].append((_capitalize(english), vietnamese))

    stages: list[dict] = []
    for level in CEFR_LEVELS:
        pending = by_level[level]
        number = 0
        while len(pending) >= PAIRS_PER_STAGE:
            chosen, deferred, meanings = [], [], set()
            for english, vietnamese in pending:
                if len(chosen) < PAIRS_PER_STAGE and vietnamese.lower() not in meanings:
                    chosen.append((english, vietnamese))
                    meanings.add(vietnamese.lower())
                else:
                    deferred.append((english, vietnamese))
            if len(chosen) < PAIRS_PER_STAGE:
                break
            number += 1
            stages.append(
                {
                    "code": f"{CODE_PREFIX}{level.lower()}-{number:03d}",
                    "title_vi": f"Từ vựng {level} · {number}",
                    "subtitle_vi": f"{PAIRS_PER_STAGE} từ Oxford thông dụng cấp {level}",
                    "symbol": LEVEL_SYMBOLS[level],
                    "level": level,
                    "pairs": chosen,
                }
            )
            pending = deferred
    return stages
