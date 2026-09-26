"""Nạp toàn bộ nội dung kỹ năng từ Data/REVIEW_skills.xlsx (nguồn sự thật duy nhất sau 2026-09-21).

  python manage.py import_review_skills                       # ../Data/REVIEW_skills.xlsx cạnh Backend/
  python manage.py import_review_skills --xlsx /path/file.xlsx --only speaking,listening
  python manage.py import_review_skills --dry-run             # chạy trong transaction rồi rollback

9 sheet → model: Luyện nói (ShadowingDeck/Sentence) · Luyện nghe (ListeningTopic/Item) · Đọc hiểu
(Reading/Sentence/Question) · Ngữ pháp (GrammarPoint/Example/Exercise) · IPA (IPASound) · Gốc từ vựng
(WordRoot) · Từ vựng + Danh mục (VocabularyDeckCollection/Deck/Item, Vocabulary/Example) · Video
(VideoCategory/Video) · Phụ đề chi tiết (VideoSubtitle) · Tài khoản ban đầu (User/UserProfile, huy hiệu,
khung avatar, XP tuần). Level tạo nếu chưa có. Chạy lại là upsert theo khoá tự nhiên; riêng từ vựng
xoá-nạp lại theo ContentSource `review_skills`, video tuyển chọn không còn trong sheet bị xoá, phụ đề thay
trọn từng video, tài khoản đã có giữ nguyên mật khẩu. Audio: URL đầy đủ trên CDN → path R2 tương đối.
"""

import re
import urllib.request
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import cmudict
import openpyxl
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.services import ensure_profile
from apps.common.learning_goals import GOAL_COLUMN, deck_goals, parse_goals, video_category_goals
from apps.common.models import LearningGoal
from apps.content import models as m
from apps.content.ipa_data import ALL_SOUNDS
from apps.content.phonemics import sentence_ipa
from apps.content.video_transcript import SubtitleDraft, replace_video_subtitles, sentence_to_ipa
from apps.gamification.models import Badge, ShopItem, UserBadge, UserCosmetic
from apps.gamification.services import current_week, ensure_league_membership
from apps.learning.api import _AVATAR_TYPES, upload_avatar
from apps.learning.models import WeeklyStat

SHEETS = {
    "speaking": "Luyện nói",
    "listening": "Luyện nghe",
    "reading": "Đọc hiểu",
    "grammar": "Ngữ pháp",
    "ipa": "IPA",
    "roots": "Gốc từ vựng",
    "vocab": "Từ vựng",
    "video": "Video (Bài học Tuyển chọn)",
    "subtitles": "Video (Phụ đề chi tiết)",
    "accounts": "Tài khoản (Ban đầu)",
}
PALETTE = ["#4F46E5", "#22C55E", "#FF6B57", "#38BDF8", "#7C3AED", "#F59E0B"]
SECONDS_PER_SENTENCE = 12
SECONDS_PER_ITEM = 10
LEVELS = [
    ("A1", "Sơ cấp", "Bắt đầu nền tảng", "Cơ bản", 1, 600, True),
    ("A2", "Sơ trung cấp", "Xây nền vững chắc", "Câu ngắn", 2, 800, True),
    (
        "B1",
        "Trung cấp",
        "Giao tiếp tự tin",
        "Giao tiếp tự tin về các chủ đề quen thuộc",
        3,
        1200,
        True,
    ),
    (
        "B2",
        "Trung cao cấp",
        "Trôi chảy nâng cao",
        "Thảo luận trôi chảy, trình bày ý kiến rõ ràng",
        4,
        2000,
        True,
    ),
    (
        "C1",
        "Cao cấp",
        "Thành thạo học thuật",
        "Dùng ngôn ngữ linh hoạt trong công việc, học thuật",
        5,
        3200,
        True,
    ),
    ("C2", "Thành thạo", "Gần như bản xứ", "Sử dụng gần như người bản xứ", 6, 5000, True),
]
TOPIC_VI = {
    "education": "Giáo dục",
    "travel": "Du lịch",
    "business": "Công sở",
    "health": "Sức khoẻ",
    "technology": "Công nghệ",
    "environment": "Môi trường",
    "culture": "Văn hoá",
    "science": "Khoa học",
    "food": "Ẩm thực",
    "family": "Gia đình",
    "sports": "Thể thao",
    "work": "Công việc",
    "society": "Xã hội",
    "entertainment": "Giải trí",
    "history": "Lịch sử",
    "daily-life": "Đời sống",
    "shopping": "Mua sắm",
    "nature": "Thiên nhiên",
    "art": "Nghệ thuật",
    "economy": "Kinh tế",
    "psychology": "Tâm lý",
}
POS_MAP = {
    "noun": "n",
    "verb": "v",
    "adjective": "adj",
    "adverb": "adv",
    "preposition": "prep",
    "pronoun": "pron",
    "conjunction": "conj",
    "determiner": "det",
    "interjection": "excl",
    "modal verb": "modal",
    "idiom": "phr",
    "phrase": "phr",
    "phrasal verb": "phr",
    "phrasal_verb": "phr",
    "collocation": "phr",
    "abbreviation": "phr",
    "plural_nouns": "n",
    "adjective__adverb": "adj",
    "verb/noun": "v",
    "adjective/verb": "adj",
}
DECK_COLLECTIONS = [  # (code, title_vi, chip, [từ khoá trong mã bộ])
    ("oxford", "Từ vựng Oxford", "Oxford", ["oxford"]),
    ("ielts", "Luyện thi IELTS", "IELTS", ["ielts"]),
    ("toeic", "Luyện thi TOEIC", "TOEIC", ["toeic"]),
    ("exam", "Ôn thi & học thuật", "Luyện thi", ["exam", "sat", "toefl", "entrance"]),
    ("popular", "Bộ sưu tập phổ biến", "Phổ biến", []),
]
ROOT_KIND = {"Tiền tố": "prefix", "Gốc": "root", "Hậu tố": "suffix"}
VIDEO_FEATURED_PER_CATEGORY = 2


def cell(v) -> str:
    return "" if v is None else str(v).strip()


def audio_path(url: str) -> str:
    """URL CDN đầy đủ → path R2 tương đối (AccentAudio lưu path, API ghép R2_PUBLIC_BASE)."""
    url = cell(url)
    if not url:
        return ""
    for base in (settings.R2_PUBLIC_BASE, "https://cdn.sayfully.com"):
        base = (base or "").rstrip("/")
        if base and url.startswith(base + "/"):
            return url[len(base) + 1 :]
    return url


def is_free(v) -> bool:
    return not cell(v).lower().startswith("premium")


def number(v) -> int:
    """'Level 9' → 9 · '42 ngày' → 42 · '1,850' → 1850."""
    return int(re.sub(r"\D", "", cell(v)) or 0)


def phase_no(v) -> int:
    mt = re.match(r"\s*(\d)", cell(v))
    return int(mt.group(1)) if mt else 0


def split_options(text: str) -> list[str]:
    """'A. try / B. dry / C. cry / D. tie' → ['try', 'dry', 'cry', 'tie']."""
    parts = re.split(r"\s+/\s+(?=[A-D]\.\s)", cell(text))
    return [re.sub(r"^[A-D]\.\s*", "", p).strip() for p in parts if p.strip()]


def answer_idx(letter: str) -> int:
    letter = cell(letter).upper()[:1]
    return "ABCD".index(letter) if letter in "ABCD" else 0


def parse_quiz_block(text: str) -> tuple[str, list[str], int, str]:
    """Ô 'VI / Lựa chọn → Đáp án · Giải thích' (ngữ pháp, gốc từ): dòng đầu = đề VI;
    dòng 'A. … / B. … ➔ Đáp án: X'; '💡 Giải thích: …'. Trả về (prompt_vi, options, answer_index, explanation)."""
    lines = [ln.strip() for ln in cell(text).splitlines() if ln.strip()]
    prompt, options, answer, explanation = "", [], 0, ""
    expl_lines: list[str] = []
    for ln in lines:
        if "➔ Đáp án:" in ln and re.match(r"^[A-D]\.", ln):
            opts, ans = ln.split("➔ Đáp án:", 1)
            options = split_options(opts)
            answer = answer_idx(ans)
        elif ln.startswith("💡"):
            expl_lines.append(re.sub(r"^💡\s*(Giải thích:)?\s*", "", ln))
        elif expl_lines:
            expl_lines.append(ln)
        elif not prompt:
            prompt = ln
    explanation = " ".join(expl_lines).strip()
    return prompt, options, answer, explanation


def parse_order_block(text: str) -> tuple[str, list[str], str, str]:
    """X2: 'Sắp xếp thành câu đúng (…):' · 'Các từ cần sắp xếp: [a / b / c]' · '💡 Giải thích: ➔ Câu hoàn chỉnh: S …'."""
    lines = [ln.strip() for ln in cell(text).splitlines() if ln.strip()]
    prompt = lines[0] if lines else ""
    words: list[str] = []
    answer = ""
    expl: list[str] = []
    for ln in lines[1:]:
        mt = re.search(r"\[(.+)\]", ln)
        if ln.startswith("Các từ cần sắp xếp") and mt:
            words = [w.strip() for w in mt.group(1).split(" / ") if w.strip()]
            continue
        ln = re.sub(r"^💡\s*(Giải thích:)?\s*", "", ln)
        mt = re.match(r"➔\s*Câu hoàn chỉnh:\s*(.+)$", ln)
        if mt:
            answer = mt.group(1).strip()
            continue
        expl.append(ln)
    return prompt, words, answer, " ".join(expl).strip()


def parse_mistakes(text: str) -> tuple[str, str, str, str]:
    """'⚠️ Lỗi thường gặp: …' · '❌ Sai: X  ➔  ✔️ Đúng: Y' · '💡 Mẹo vàng: …' → (common, wrong, right, tip)."""
    common = wrong = right = tip = ""
    for ln in cell(text).splitlines():
        ln = ln.strip()
        if ln.startswith("⚠️"):
            common = re.sub(r"^⚠️\s*(Lỗi thường gặp:)?\s*", "", ln)
        elif ln.startswith("❌"):
            mt = re.match(r"❌\s*Sai:\s*(.*?)\s*➔\s*✔️\s*Đúng:\s*(.*)$", ln)
            if mt:
                wrong, right = mt.group(1).strip(), mt.group(2).strip()
        elif ln.startswith("💡"):
            tip = re.sub(r"^💡\s*(Mẹo vàng:)?\s*", "", ln)
    return common, wrong, right, tip


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+(?=[\"'“(A-Z0-9])", cell(text).replace("\n", " "))
    return [p.strip() for p in parts if p.strip()]


def parse_reading_quiz(text: str) -> list[dict]:
    """'[Câu n] hỏi' · 4 dòng 'A. … (*)' · '➔ Đáp án: B | trích dẫn' — mỗi block cách nhau dòng trống."""
    out = []
    for block in re.split(r"\n\s*\n", cell(text)):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines or not lines[0].startswith("[Câu"):
            continue
        q = re.sub(r"^\[Câu\s*\d+\]\s*", "", lines[0])
        options, answer, explanation = [], 0, ""
        for ln in lines[1:]:
            if re.match(r"^[A-D]\.\s", ln):
                options.append(re.sub(r"^[A-D]\.\s*", "", ln).replace("(*)", "").strip())
            elif ln.startswith("➔ Đáp án:"):
                rest = ln[len("➔ Đáp án:") :].strip()
                letter, _, expl = rest.partition("|")
                answer = answer_idx(letter)
                explanation = expl.strip()
        if q and options:
            out.append({"q": q, "options": options, "answer": answer, "explanation": explanation})
    return out


def parse_word_list(text: str) -> list[dict]:
    """'word /ipa/ (nghĩa), word2 /ipa/ (nghĩa)' hoặc bullet '• word /ipa/: nghĩa (gốc: base)'."""
    out = []
    pattern = re.compile(
        r"^(?P<word>[A-Za-z][A-Za-z' -]*?)\s*(?P<ipa>/[^/]+/)\s*[:(]?\s*(?P<rest>.*?)\)?$"
    )
    for chunk in re.split(r",\s*(?=[A-Za-z' -]+\s*/)|\n", cell(text)):
        chunk = chunk.strip().lstrip("•").strip()
        mt = pattern.match(chunk)
        if not mt:
            continue
        meaning = mt.group("rest").strip()
        base = ""
        mb = re.search(r"\(gốc:\s*([^)]+)\)?", meaning)
        if mb:
            base = mb.group(1).strip()
            meaning = meaning[: mb.start()].strip()
        out.append(
            {
                "word": mt.group("word").strip(),
                "ipa": mt.group("ipa").strip(),
                "meaning_vi": meaning,
                "base": base,
            }
        )
    return out


CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]
EXAMPLE_FIELDS = ("example_en", "example_vi", "ex_audio_us", "ex_audio_uk")
FILL_FIELDS = ("definition_en", "definition_vi", "ipa_uk", "ipa_us", "audio_uk_path", "audio_us_path")


def merge_vocab_entries(entries: list[dict]) -> dict:
    """Gộp các dòng cùng (từ, loại từ) từ nhiều bộ thành 1 mục từ điển.

    Cấp CEFR chỉ lấy từ các bộ Oxford (cấp thấp nhất nếu từ có ở nhiều cấp). Cấp của các bộ khác là
    cấp của cả bộ (IELTS, SAT, thành ngữ… đều ghi A1), không phải độ khó của từng từ, nên từ chỉ có
    ở những bộ đó không được gán cấp. Dòng chính là dòng Oxford, không có thì dòng có nghĩa dài
    nhất; trường còn trống lấy từ các dòng khác, câu ví dụ lấy nguyên cụm từ cùng một dòng.
    """
    oxford = [e for e in entries if e["deck"].startswith("oxford-")]
    primary = oxford[0] if oxford else max(entries, key=lambda e: len(e["meaning_vi"]))
    merged = dict(primary)
    for field in FILL_FIELDS:
        if not merged[field]:
            merged[field] = next((e[field] for e in entries if e[field]), "")
    if not merged["example_en"]:
        donor = next((e for e in entries if e["example_en"]), None)
        if donor:
            merged.update({f: donor[f] for f in EXAMPLE_FIELDS})
    levels = sorted({e["level_code"] for e in oxford if e["level_code"] in CEFR_ORDER}, key=CEFR_ORDER.index)
    merged["level_code"] = levels[0] if levels else None
    merged["sense"] = ""
    return merged


class Command(BaseCommand):
    help = "Nạp Data/REVIEW_skills.xlsx vào DB (nguồn sự thật duy nhất)."

    def add_arguments(self, parser):
        default = Path(__file__).resolve().parents[5] / "Data" / "REVIEW_skills.xlsx"
        parser.add_argument("--xlsx", default=str(default))
        parser.add_argument("--only", default="", help=",".join(SHEETS))
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        path = Path(opts["xlsx"]).resolve()
        if not path.exists():
            raise CommandError(f"Không thấy {path}")
        only = {x.strip() for x in opts["only"].split(",") if x.strip()} or set(SHEETS)
        unknown = only - set(SHEETS)
        if unknown:
            raise CommandError(f"--only không hợp lệ: {', '.join(sorted(unknown))}")
        self.wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        self.cmu = None
        self.dry_run = opts["dry_run"]
        with transaction.atomic():
            self.levels = self.ensure_levels()
            for key in SHEETS:
                if key in only:
                    getattr(self, f"import_{key}")()
            if opts["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("dry-run: đã rollback"))

    # ------------------------------------------------------------------ helpers
    def rows(self, key: str):
        ws = self.wb[SHEETS[key]]
        it = ws.iter_rows(values_only=True)
        head = [cell(h) for h in next(it)]
        for r in it:
            if r is None or all(v is None or cell(v) == "" for v in r):
                continue
            yield dict(zip(head, r, strict=False))

    def level(self, code: str) -> m.Level:
        lv = self.levels.get(cell(code).upper())
        if not lv:
            raise CommandError(f"Level không hợp lệ: {code!r}")
        return lv

    def ensure_levels(self) -> dict[str, m.Level]:
        out = {}
        for code, name_vi, tier, desc, order, target, free in LEVELS:
            out[code], _ = m.Level.objects.update_or_create(
                code=code,
                defaults={
                    "name_vi": name_vi,
                    "tier_label": tier,
                    "description_vi": desc,
                    "order": order,
                    "word_target": target,
                    "is_free": free,
                },
            )
        return out

    def ipa_of(self, text: str) -> str:
        if self.cmu is None:
            self.cmu = cmudict.dict()
        return sentence_ipa(text, self.cmu)[:512]

    def subtitle_ipa(self, text: str) -> str:
        if self.cmu is None:
            self.cmu = cmudict.dict()
        return sentence_to_ipa(text, self.cmu)[0][:512]

    def log(self, msg: str):
        self.stdout.write(self.style.SUCCESS(msg))

    # ------------------------------------------------------------------ 1. Luyện nói
    def import_speaking(self):
        decks: dict[str, dict] = {}
        for r in self.rows("speaking"):
            code = cell(r["Deck"])
            d = decks.setdefault(
                code,
                {
                    "level": r["Level"],
                    "title_en": r["Chủ đề EN"],
                    "title_vi": r["Chủ đề VI"],
                    "focus_vi": r["Trọng tâm bài (focus_vi)"],
                    "free": [],
                    "rows": [],
                },
            )
            d["free"].append(is_free(r["Phân hạng"]))
            d["rows"].append(r)
        n_sent = 0
        for code, d in decks.items():
            level = self.level(d["level"])
            order = int(code.split("-")[-1])
            bg_url = cell(d["rows"][0].get("Link ảnh background (CDN URL)", ""))
            deck, _ = m.ShadowingDeck.objects.update_or_create(
                level=level,
                order=order,
                defaults={
                    "title_en": cell(d["title_en"])[:128],
                    "title_vi": cell(d["title_vi"])[:128],
                    "focus_vi": cell(d["focus_vi"])[:128],
                    "est_seconds": len(d["rows"]) * SECONDS_PER_SENTENCE,
                    "color": PALETTE[(order - 1) % len(PALETTE)],
                    "background_url": bg_url[:255],
                    "is_free": all(d["free"]),
                },
            )
            deck.sentences.all().delete()
            rows = []
            for r in d["rows"]:
                stress = [w.strip() for w in re.split(r"[,;]", cell(r["Từ nhấn"])) if w.strip()]
                rows.append(
                    m.ShadowingSentence(
                        deck=deck,
                        order=int(cell(r["#"])),
                        text_en=cell(r["Câu luyện nói (EN)"])[:512],
                        ipa=cell(r["Phiên âm IPA"])[:512],
                        text_vi=cell(r["Bản dịch (VI)"])[:512],
                        speaking_goal_vi=cell(r["Chỉ dẫn sư phạm"])[:255],
                        highlights=[{"text": w, "kind": "primary_stress"} for w in stress],
                        phase=phase_no(r["Pha sư phạm"]),
                        speech_act_vi=cell(r["Chức năng (Speech Act)"])[:128],
                        context_vi=cell(r["Ngữ cảnh / Lời thoại đối tác"])[:255],
                        phonetic_note_vi=cell(r["Hiện tượng ngữ âm"])[:255],
                        audio_us_path=audio_path(r["Audio US"]),
                        audio_uk_path=audio_path(r["Audio UK"]),
                    )
                )
            m.ShadowingSentence.objects.bulk_create(rows)
            n_sent += len(rows)
        self.log(f"Luyện nói: {len(decks)} deck · {n_sent} câu")

    # ------------------------------------------------------------------ 2. Luyện nghe
    def import_listening(self):
        topics: dict[str, dict] = {}
        for r in self.rows("listening"):
            code = cell(r["Chủ đề"])
            t = topics.setdefault(
                code, {"level": r["Level"], "title_vi": r["Tiêu đề VI"], "free": [], "rows": []}
            )
            t["free"].append(is_free(r["Phân hạng"]))
            t["rows"].append(r)
        n_items = 0
        for code, t in topics.items():
            level = self.level(t["level"])
            order = int(code.split("-")[-1])
            bg_url = cell(t["rows"][0].get("Link ảnh background (CDN URL)", ""))
            topic, _ = m.ListeningTopic.objects.update_or_create(
                level=level,
                order=order,
                defaults={
                    "title_vi": cell(t["title_vi"])[:128],
                    "est_seconds": len(t["rows"]) * SECONDS_PER_ITEM,
                    "color": PALETTE[(order - 1) % len(PALETTE)],
                    "icon_url": bg_url[:255],
                    "background_url": bg_url[:255],
                    "is_free": all(t["free"]),
                },
            )
            topic.items.all().delete()
            rows = []
            for r in t["rows"]:
                shown = cell(r["Câu hiển thị khuyết"]).split()
                blank = next((i for i, w in enumerate(shown) if "[_____]" in w), None)
                rows.append(
                    m.ListeningItem(
                        topic=topic,
                        order=int(cell(r["#"])),
                        text_en=cell(r["Câu nghe hoàn chỉnh (EN)"])[:512],
                        text_vi=cell(r["Bản dịch (VI)"])[:512],
                        blank_index=blank,
                        options=split_options(r["Lựa chọn (A, B, C, D)"]),
                        answer_index=answer_idx(r["Đáp án đúng"]),
                        phase=phase_no(r["Pha sư phạm"]),
                        skill_vi=cell(r["Kỹ năng nghe"])[:128],
                        word_class_vi=cell(r["Từ loại khuyết"])[:64],
                        trap_vi=cell(r["Loại bẫy nghe"])[:128],
                        tip_vi=cell(r["Mẹo nghe sư phạm"]),
                        audio_us_path=audio_path(r["Audio US"]),
                        audio_uk_path=audio_path(r["Audio UK"]),
                    )
                )
            m.ListeningItem.objects.bulk_create(rows)
            n_items += len(rows)
        self.log(f"Luyện nghe: {len(topics)} chủ đề · {n_items} câu")

    # ------------------------------------------------------------------ 3. Đọc hiểu
    def import_reading(self):
        order_by_level: dict[str, int] = defaultdict(int)
        vocab_by_ref = {
            v.source_ref: v
            for v in m.Vocabulary.objects.exclude(source_ref="").only("id", "source_ref")
        }
        n_sent = n_q = n_kw = 0
        n_read = 0
        for r in self.rows("reading"):
            level = self.level(r["Level"])
            order_by_level[level.code] += 1
            topic_code = cell(r["Chủ đề"]).lower()
            topic = None
            if topic_code:
                topic, _ = m.Topic.objects.get_or_create(
                    code=topic_code[:48],
                    defaults={
                        "name_vi": TOPIC_VI.get(topic_code, topic_code.replace("-", " ").title())[
                            :64
                        ],
                        "name_en": topic_code.replace("-", " ").title()[:64],
                    },
                )
            en = split_sentences(r["Đoạn văn Tiếng Anh (Full Passage)"])
            vi = split_sentences(r["Đoạn văn Tiếng Việt (Bản dịch)"])
            cover = cell(r.get("Link ảnh background (CDN URL)", ""))
            reading, _ = m.Reading.objects.update_or_create(
                level=level,
                order=order_by_level[level.code],
                defaults={
                    "code": cell(r["Mã bài"])[:48],
                    "is_free": is_free(r["Phân hạng"]),
                    "title_en": cell(r["Tiêu đề EN"])[:128],
                    "title_vi": cell(r["Tiêu đề VI"])[:128],
                    "topic": topic,
                    "cover_path": cover[:255],
                    "est_minutes": max(1, round(sum(len(s.split()) for s in en) / 120)),
                },
            )
            n_read += 1
            kws = [
                vocab_by_ref[k.strip()]
                for k in cell(r["Từ khoá (Keywords)"]).split(",")
                if k.strip() in vocab_by_ref
            ]
            reading.keywords.set(kws)
            n_kw += len(kws)
            reading.sentences.all().delete()
            rows = []
            for i, s_en in enumerate(en, 1):
                # Bản dịch tách câu độc lập; lệch số câu thì câu cuối gom phần VI còn lại.
                s_vi = vi[i - 1] if i < len(en) and i - 1 < len(vi) else " ".join(vi[i - 1 :])
                rows.append(
                    m.ReadingSentence(
                        reading=reading,
                        order=i,
                        text_en=s_en[:512],
                        text_vi=s_vi[:512],
                        ipa=self.ipa_of(s_en),
                    )
                )
            m.ReadingSentence.objects.bulk_create(rows)
            n_sent += len(rows)
            reading.questions.all().delete()
            quiz = parse_reading_quiz(
                r["Bộ 4 Quiz Đọc Hiểu (Câu hỏi · Lựa chọn · Đáp án · Giải thích)"]
            )
            m.ReadingQuestion.objects.bulk_create(
                [
                    m.ReadingQuestion(
                        reading=reading,
                        order=i,
                        question_en=q["q"][:512],
                        options=q["options"],
                        answer_index=q["answer"],
                        explanation_vi=q["explanation"][:512],
                    )
                    for i, q in enumerate(quiz, 1)
                ]
            )
            n_q += len(quiz)
        self.log(f"Đọc hiểu: {n_read} bài · {n_sent} câu · {n_q} câu hỏi · {n_kw} từ khoá khớp")

    # ------------------------------------------------------------------ 4. Ngữ pháp
    def import_grammar(self):
        points: dict[str, dict] = {}
        for r in self.rows("grammar"):
            gid = cell(r["ID"])
            p = points.setdefault(gid, {"g": None, "examples": [], "exercises": []})
            tag = cell(r["#"])
            if tag == "G":
                p["g"] = r
            elif tag.startswith("E"):
                p["examples"].append(r)
            elif tag.startswith("X"):
                p["exercises"].append(r)
        n_ex = n_x = 0
        kinds = {"1": "choice", "2": "order", "3": "blank", "4": "fix"}
        for gid, p in points.items():
            g = p["g"]
            if g is None:
                self.stderr.write(f"  Ngữ pháp {gid}: thiếu dòng G, bỏ qua")
                continue
            common, wrong, right, tip = parse_mistakes(g["Lỗi người Việt hay gặp & Mẹo"])
            level = self.level(g["Level"])
            point, _ = m.GrammarPoint.objects.update_or_create(
                level=level,
                order=int(cell(g["Thứ tự"])),
                defaults={
                    "category": cell(g["Chuyên mục"])[:48],
                    "title_vi": cell(g["Tiêu đề VI"])[:160],
                    "formula": cell(g["Công thức"])[:160],
                    "explanation_vi": cell(g["Giải thích ngữ pháp"]),
                    "common_mistake_vi": common,
                    "mistake_wrong": wrong[:160],
                    "mistake_right": right[:160],
                    "note_vi": tip,
                    "source_ref": cell(g["Ref"])[:16],
                    "is_path_core": cell(g["Cốt lõi"]) == "✓",
                    "lesson_code": cell(g["Bài học"])[:48],
                },
            )
            point.examples.all().delete()
            m.GrammarExample.objects.bulk_create(
                [
                    m.GrammarExample(
                        grammar_point=point,
                        order=i,
                        text_en=cell(e["EN / Đề bài thực hành"])[:255],
                        text_vi=cell(e["VI / Lựa chọn → Đáp án · Giải thích"])[:255],
                        ipa=cell(e["Dạng bài / IPA"])[:255]
                        if cell(e["Dạng bài / IPA"]).startswith("/")
                        else "",
                        audio_us_path=audio_path(e["Audio US"]),
                        audio_uk_path=audio_path(e["Audio UK"]),
                    )
                    for i, e in enumerate(p["examples"], 1)
                ]
            )
            n_ex += len(p["examples"])
            point.exercises.all().delete()
            rows = []
            for i, x in enumerate(p["exercises"], 1):
                kind = kinds.get(cell(x["Dạng bài / IPA"])[:1], "choice")
                body = x["VI / Lựa chọn → Đáp án · Giải thích"]
                if kind == "order":
                    prompt_vi, options, answer_text, expl = parse_order_block(body)
                    answer = 0
                else:
                    prompt_vi, options, answer, expl = parse_quiz_block(body)
                    answer_text = ""
                rows.append(
                    m.GrammarExercise(
                        grammar_point=point,
                        order=i,
                        kind=kind,
                        prompt_en=cell(x["EN / Đề bài thực hành"])[:512],
                        prompt_vi=prompt_vi[:512],
                        options=options,
                        answer_index=answer,
                        answer_text=answer_text[:255],
                        explanation_vi=expl,
                        is_free=is_free(x["Phân hạng"]),
                    )
                )
            m.GrammarExercise.objects.bulk_create(rows)
            n_x += len(rows)
        self.log(f"Ngữ pháp: {len(points)} điểm · {n_ex} ví dụ · {n_x} bài tập")

    # ------------------------------------------------------------------ 5. IPA
    def import_ipa(self):
        canon = {s["symbol"]: s for s in ALL_SOUNDS}
        n = 0
        for r in self.rows("ipa"):
            symbol = cell(r["Ký hiệu âm (IPA)"]).strip("/")
            base = canon.get(symbol)
            if not base:
                self.stderr.write(f"  IPA {symbol!r} không có trong ipa_data, bỏ qua")
                continue
            examples = parse_word_list(r["Từ chứa âm tiêu biểu"])
            pair_other = (
                cell(r["Cặp âm dễ nhầm"]).split("vs")[-1].strip().strip("/")
                if "vs" in cell(r["Cặp âm dễ nhầm"])
                else ""
            )
            pair_words = [
                w["word"]
                for w in parse_word_list(
                    cell(r["Từ ví dụ phân biệt (Minimal Pairs)"]).replace("➔", ",")
                )
            ][:2]
            drill = cell(r["Câu luyện âm thực hành (Drill / Tongue Twister)"]).splitlines()
            mouth_img = cell(r.get("Link ảnh khẩu hình (CDN URL)", ""))
            m.IPASound.objects.update_or_create(
                symbol=symbol,
                defaults={
                    "mouth_image_path": mouth_img[:255],
                    "kind": base["kind"],
                    "group": base["group"],
                    "order": int(cell(r["STT"]) or n + 1),
                    "category_vi": cell(r["Phân loại âm"])[:64],
                    "category_en": base.get("category_en", "")[:64],
                    "acoustic_vi": cell(r["Đặc tính âm học"])[:64],
                    "description_vi": (
                        base.get("description_vi") or cell(r["Mô tả chi tiết cách phát âm"])
                    )[:255],
                    "articulation_vi": cell(r["Mô tả chi tiết cách phát âm"]),
                    "lips_vi": cell(r["Khẩu hình: Khóe miệng & Môi"])[:64],
                    "tongue_vi": cell(r["Khẩu hình: Đầu lưỡi & Vị trí lưỡi"])[:64],
                    "tip_vi": cell(r["Mẹo vàng phân biệt & Lỗi người Việt"])[:255],
                    "sample_words": [e["word"] for e in examples],
                    "examples": [
                        {"word": e["word"], "ipa": e["ipa"], "meaning_vi": e["meaning_vi"]}
                        for e in examples
                    ],
                    "minimal_pair": {"other": pair_other, "words": pair_words}
                    if pair_other and len(pair_words) == 2
                    else {},
                    "practice_words": {
                        "initial": parse_word_list(r["Luyện âm: Vị trí đầu từ (Initial)"]),
                        "medial": parse_word_list(r["Luyện âm: Vị trí giữa từ (Medial)"]),
                        "final": parse_word_list(r["Luyện âm: Vị trí cuối từ (Final)"]),
                    },
                    "drill_en": (drill[0] if drill else "")[:255],
                    "drill_vi": (drill[1].strip("()") if len(drill) > 1 else "")[:255],
                    "audio_us_path": audio_path(r["Audio drill US"]),
                    "audio_uk_path": audio_path(r["Audio drill UK"]),
                },
            )
            n += 1
        self.log(f"IPA: {n} âm")

    # ------------------------------------------------------------------ 6. Gốc từ vựng
    def import_roots(self):
        roots: dict[str, dict] = {}
        groups: dict[str, int] = {}
        for r in self.rows("roots"):
            key = cell(r["STT"])
            root = roots.setdefault(key, {"r": None, "practice": []})
            if cell(r["#"]) == "R":
                root["r"] = r
                groups.setdefault(cell(r["Nhóm ý nghĩa"]), len(groups) + 1)
            else:
                root["practice"].append(r)
        n = 0
        for key, root in roots.items():
            r = root["r"]
            if r is None:
                continue
            kind = next(
                (v for k, v in ROOT_KIND.items() if cell(r["Loại gốc"]).startswith(k)), "root"
            )
            practice = []
            for p in root["practice"]:
                head = cell(p["Từ mục tiêu & Phân tách cấu trúc"])
                word = head.split("➔")[0].strip()
                base = head.split("+")[-1].strip() if "+" in head else ""
                q, options, answer, expl = parse_quiz_block(
                    p["Đề bài & 4 Lựa chọn A/B/C/D ➔ Đáp án · Giải thích"]
                )
                ex = cell(p["Họ từ phái sinh & Câu ví dụ thực tế"]).splitlines()
                meaning = options[answer] if options and answer < len(options) else ""
                practice.append(
                    {
                        "word": word,
                        "base": base,
                        "ipa": cell(p["Phiên âm IPA"]),
                        "meaning_vi": meaning,
                        "question_vi": q,
                        "options": options,
                        "answer_index": answer,
                        "explanation_vi": expl,
                        "tip_vi": cell(p["Mẹo ghi nhớ từ Bé Long"]),
                        "example_en": ex[0].strip() if ex else "",
                        "example_vi": ex[1].strip().strip("()") if len(ex) > 1 else "",
                        "audio_us_path": audio_path(p["Audio US"]),
                        "audio_uk_path": audio_path(p["Audio UK"]),
                    }
                )
            samples = parse_word_list(r["Đề bài & 4 Lựa chọn A/B/C/D ➔ Đáp án · Giải thích"])
            for s_ in samples:
                match = next((p for p in practice if p["word"].lower() == s_["word"].lower()), None)
                if match:
                    s_["audio_us_path"], s_["audio_uk_path"] = (
                        match["audio_us_path"],
                        match["audio_uk_path"],
                    )
            m.WordRoot.objects.update_or_create(
                kind=kind,
                text=cell(r["Gốc từ / Ký hiệu"])[:32],
                defaults={
                    "meaning_vi": cell(r["Ý nghĩa cốt lõi"])[:128],
                    "group_vi": cell(r["Nhóm ý nghĩa"])[:64],
                    "group_order": groups.get(cell(r["Nhóm ý nghĩa"]), 0),
                    "order": int(key),
                    "effect_vi": cell(r["Dạng bài tập / Tác động ngữ nghĩa"])[:128],
                    "mnemonic_vi": cell(r["Mẹo ghi nhớ từ Bé Long"]),
                    "samples": samples,
                    "family": [
                        w.strip()
                        for w in cell(r["Họ từ phái sinh & Câu ví dụ thực tế"]).split(",")
                        if w.strip()
                    ],
                    "practice": practice,
                    "practice_is_free": all(is_free(p["Phân hạng"]) for p in root["practice"])
                    if root["practice"]
                    else True,
                },
            )
            n += 1
        self.log(f"Gốc từ: {n} gốc")

    # ------------------------------------------------------------------ 7. Từ vựng
    def import_vocab(self):
        source, _ = m.ContentSource.objects.get_or_create(
            code="review_skills", defaults={"name": "REVIEW_skills.xlsx", "usage": "content"}
        )
        deleted, _ = m.Vocabulary.objects.filter(source=source).delete()
        collections = {}
        for i, (code, title, chip, _kw) in enumerate(DECK_COLLECTIONS, 1):
            collections[code], _ = m.VocabularyDeckCollection.objects.update_or_create(
                code=code, defaults={"title_vi": title, "chip_label_vi": chip, "order": i}
            )

        def collection_for(deck_code: str):
            for code, _t, _c, kws in DECK_COLLECTIONS:
                if any(k in deck_code for k in kws):
                    return collections[code]
            return collections["popular"]

        catalog = {}
        for r in self.rows_named("Từ vựng (Danh mục)"):
            catalog[cell(r["Mã bộ (Slug)"])] = r
        decks: dict[str, m.VocabularyDeck] = {}
        for i, (code, r) in enumerate(catalog.items(), 1):
            decks[code], _ = m.VocabularyDeck.objects.update_or_create(
                code=code[:64],
                defaults={
                    "collection": collection_for(code),
                    "title_vi": cell(r["Tên bộ từ"])[:128],
                    "cover_title": cell(r["Tên bộ từ"])[:64],
                    "badge_vi": cell(r["Trình độ (Level)"])[:32],
                    "level": self.level(r["Trình độ (Level)"]),
                    "order": i,
                    "is_free": is_free(r["Phân hạng"]),
                    "description_vi": cell(r["Đặc điểm nội dung & Mục tiêu"])[:255],
                    "learning_goals": parse_goals(cell(r.get(GOAL_COLUMN))) or deck_goals(code),
                },
            )
            decks[code].items.all().delete()

        # Mỗi (từ, loại từ) là 1 Vocabulary dù xuất hiện ở nhiều bộ với cách ghi nghĩa khác nhau;
        # bộ nào cũng vẫn giữ thẻ của mình. Cấp CEFR xem merge_vocab_entries.
        grouped: dict[tuple, list[dict]] = defaultdict(list)
        items: list[tuple] = []  # (deck_code, key, order, unit)
        order_in_deck: dict[str, int] = defaultdict(int)
        for r in self.rows("vocab"):
            deck_code = cell(r["Mã bộ (Deck)"])
            if deck_code not in decks:
                self.stderr.write(f"  Từ vựng: bộ {deck_code!r} không có trong Danh mục, bỏ qua")
                continue
            head = cell(r["Từ vựng (Word)"])[:64]
            pos = POS_MAP.get(cell(r["Từ loại (POS)"]).lower(), "phr")
            key = (head.lower(), pos)
            grouped[key].append(
                {
                    "deck": deck_code,
                    "level_code": cell(r["Level"]).upper(),
                    "headword": head,
                    "pos": pos,
                    "meaning_vi": cell(r["Nghĩa tiếng Việt"])[:255],
                    "definition_en": cell(r["Định nghĩa giải thích EN"]),
                    "definition_vi": cell(r["Định nghĩa giải thích VI"]),
                    "ipa_uk": cell(r["Phiên âm UK"])[:64],
                    "ipa_us": cell(r["Phiên âm US"])[:64],
                    "audio_uk_path": audio_path(r["Audio từ UK"]),
                    "audio_us_path": audio_path(r["Audio từ US"]),
                    "example_en": cell(r["Câu ví dụ EN"])[:255],
                    "example_vi": cell(r["Câu ví dụ VI"])[:255],
                    "ex_audio_us": audio_path(r["Audio ví dụ US"]),
                    "ex_audio_uk": audio_path(r["Audio ví dụ UK"]),
                }
            )
            order_in_deck[deck_code] += 1
            items.append(
                (deck_code, key, order_in_deck[deck_code], cell(r["Bài học (Unit)"])[:128])
            )
        vocab_rows: dict[tuple, dict] = {}
        for key, entries in grouped.items():
            d = merge_vocab_entries(entries)
            d["level"] = self.level(d["level_code"]) if d["level_code"] else None
            vocab_rows[key] = d

        # Từ đã có trong DB từ nguồn khác (cùng headword/pos/sense) → dùng lại, không tạo trùng.
        existing = {
            (v.headword.lower(), v.pos, v.sense): v
            for v in m.Vocabulary.objects.filter(
                headword__in={d["headword"] for d in vocab_rows.values()}
            )
        }
        to_create, key_by_identity = [], {}
        for key, d in vocab_rows.items():
            ident = (d["headword"].lower(), d["pos"], d["sense"])
            key_by_identity[ident] = key
            if ident in existing:
                continue
            to_create.append(
                m.Vocabulary(
                    headword=d["headword"],
                    pos=d["pos"],
                    sense=d["sense"],
                    level=d["level"],
                    meaning_vi=d["meaning_vi"],
                    definition_en=d["definition_en"],
                    definition_vi=d["definition_vi"],
                    ipa_uk=d["ipa_uk"],
                    ipa_us=d["ipa_us"],
                    audio_uk_path=d["audio_uk_path"],
                    audio_us_path=d["audio_us_path"],
                    source=source,
                )
            )
        m.Vocabulary.objects.bulk_create(to_create, batch_size=1000)
        by_key: dict[tuple, m.Vocabulary] = {}
        for v in m.Vocabulary.objects.filter(
            headword__in={d["headword"] for d in vocab_rows.values()}
        ):
            ident = (v.headword.lower(), v.pos, v.sense)
            if ident in key_by_identity:
                by_key[key_by_identity[ident]] = v
        examples = [
            m.VocabularyExample(
                vocabulary=by_key[key],
                order=1,
                text_en=d["example_en"],
                text_vi=d["example_vi"],
                audio_us_path=d["ex_audio_us"],
                audio_uk_path=d["ex_audio_uk"],
            )
            for key, d in vocab_rows.items()
            if d["example_en"] and by_key[key].source_id == source.pk
        ]
        m.VocabularyExample.objects.bulk_create(examples, batch_size=1000)
        seen: set[tuple] = set()
        deck_items = []
        for deck_code, key, order, unit in items:
            if (deck_code, key) in seen:
                continue
            seen.add((deck_code, key))
            deck_items.append(
                m.VocabularyDeckItem(
                    deck=decks[deck_code], vocabulary=by_key[key], order=order, group_vi=unit
                )
            )
        m.VocabularyDeckItem.objects.bulk_create(deck_items, batch_size=1000)
        self.log(
            f"Từ vựng: {len(decks)} bộ · {len(deck_items)} thẻ · {len(to_create)} từ mới · "
            f"{len(vocab_rows) - len(to_create)} từ dùng lại · {len(examples)} ví dụ (xoá {deleted} bản cũ)"
        )

    def rows_named(self, sheet: str):
        ws = self.wb[sheet]
        it = ws.iter_rows(values_only=True)
        head = [cell(h) for h in next(it)]
        for r in it:
            if r is None or all(v is None or cell(v) == "" for v in r):
                continue
            yield dict(zip(head, r, strict=False))

    # ------------------------------------------------------------------ 8. Video
    def import_video(self):
        cats = {}
        for i, r in enumerate(self.rows_named("Video (Chủ đề)"), 1):
            name = cell(r["Cụm chủ đề sư phạm"])[:48]
            slug = cell(r["Slug chủ đề"])
            cats[slug] = name
            m.VideoCategory.objects.update_or_create(
                name=name,
                defaults={
                    "slug": slug[:48],
                    "subtitle": cell(r["Đặc điểm nội dung & Mục tiêu đào tạo"])[:120],
                    "order": i,
                    "learning_goals": parse_goals(cell(r.get(GOAL_COLUMN))) or video_category_goals(slug, name),
                },
            )
        n = 0
        seen: set[str] = set()
        views_by_cat: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for r in self.rows("video"):
            yid = cell(r["YouTube ID"])
            if not yid:
                continue
            seen.add(yid)
            cat = cats.get(cell(r["Mã chủ đề"]), cell(r["Cụm chủ đề (Sayfully)"])[:48])
            views = int(re.sub(r"\D", "", cell(r["Lượt học / Lượt xem"])) or 0)
            m.Video.objects.update_or_create(
                youtube_id=yid,
                defaults={
                    "level": self.level(r["Trình độ (CEFR)"]),
                    "title_vi": cell(r["Tiêu đề tiếng Việt"])[:160],
                    "title_en": cell(r["Tên bài học (EN)"])[:160],
                    "category": cat,
                    "duration_sec": int(cell(r["Thời lượng (s)"]) or 0),
                    "is_free": is_free(r["Phân hạng"]),
                    "channel": cell(r["Kênh / Nguồn"])[:120],
                    "source": m.Video.Source.CURATED,
                    "status": m.Video.Status.READY,
                    "is_featured": False,
                    "featured_order": 0,
                },
            )
            views_by_cat[cat].append((views, yid))
            n += 1
        featured = []
        for lst in views_by_cat.values():
            featured += [yid for _, yid in sorted(lst, reverse=True)[:VIDEO_FEATURED_PER_CATEGORY]]
        for i, yid in enumerate(featured, 1):
            m.Video.objects.filter(youtube_id=yid).update(is_featured=True, featured_order=i)
        stale = m.Video.objects.filter(source=m.Video.Source.CURATED).exclude(youtube_id__in=seen)
        removed = stale.count()
        stale.delete()
        self.log(
            f"Video: {len(cats)} cụm chủ đề · {n} video · {len(featured)} nổi bật "
            f"(xoá {removed} video không còn trong sheet)"
        )

    # ------------------------------------------------------------------ 9. Phụ đề video
    def import_subtitles(self):
        by_video: dict[str, list[dict]] = defaultdict(list)
        for r in self.rows("subtitles"):
            by_video[cell(r["YouTube ID"])].append(r)
        videos = m.Video.objects.in_bulk(list(by_video), field_name="youtube_id")
        n = 0
        for yid, rows in by_video.items():
            video = videos.get(yid)
            if video is None:
                self.stderr.write(f"  Phụ đề: không có video {yid!r}, bỏ qua")
                continue
            # Sheet để trống bản dịch thì giữ bản dịch đã có trong DB cho cùng câu.
            kept_vi = dict(video.subtitles.exclude(text_vi="").values_list("text_en", "text_vi"))
            drafts = []
            for r in sorted(rows, key=lambda r: number(r["# (Thứ tự câu)"])):
                text_en = cell(r["Câu phụ đề (EN)"])[:512]
                drafts.append(
                    SubtitleDraft(
                        start_ms=number(r["Bắt đầu (ms)"]),
                        end_ms=number(r["Kết thúc (ms)"]),
                        text_en=text_en,
                        ipa=cell(r["Phiên âm ngữ âm (IPA)"])[:512] or self.subtitle_ipa(text_en),
                        text_vi=cell(r["Bản dịch tiếng Việt (VI)"])[:512]
                        or kept_vi.get(text_en, ""),
                    )
                )
            # Caption tự động hay chồng vài ms lên câu sau; cắt đuôi để qua validate_drafts.
            for i in range(len(drafts) - 1):
                if drafts[i].end_ms > drafts[i + 1].start_ms:
                    drafts[i] = replace(drafts[i], end_ms=drafts[i + 1].start_ms)
            n += replace_video_subtitles(video, drafts)
        self.log(f"Phụ đề: {n} câu · {len(videos)} video")

    # ------------------------------------------------------------------ 10. Tài khoản ban đầu
    def import_accounts(self):
        user_model = get_user_model()
        goals = {label: value for value, label in LearningGoal.choices}
        badges = {b.code: b for b in Badge.objects.all()}
        frames = {i.code: i for i in ShopItem.objects.filter(category=ShopItem.Category.COSMETIC)}
        year, week = current_week()
        today = timezone.localdate()
        n = created = 0
        for r in self.rows("accounts"):
            email = cell(r["Email"]).lower()
            user = user_model.objects.filter(email=email).first()
            if user is None:
                user = user_model.objects.create_user(
                    email=email, password=cell(r["Mật khẩu mặc định"])
                )
                created += 1
            user.full_name = cell(r["Họ và tên"])[:120]
            avatar = cell(r["Ảnh đại diện (CDN URL)"])
            if avatar and not self.dry_run and (not user.avatar_path or "://" in user.avatar_path):
                user.avatar_path = self.upload_avatar_from(user, avatar)
            user.save(update_fields=["full_name", "avatar_path"])

            streak = number(r["Streak (ngày)"])
            frame = cell(r["Mã Khung"])
            p = ensure_profile(user)
            p.level = number(r["Cấp độ"]) or 1
            p.cefr_level = cell(r["Khung CEFR"]).upper()
            p.goal_level = cell(r["Mục tiêu CEFR"]).upper()
            p.learning_goal = goals.get(cell(r["Mục tiêu học tập"]), LearningGoal.DAILY)
            p.xp_total = number(r["XP Tổng"])
            p.coins = number(r["Số xu (Coins)"])
            p.streak_current = streak
            p.streak_best = max(p.streak_best, streak)
            p.last_active_date = today
            p.accent = "UK" if "(UK)" in cell(r["Giọng phát âm"]) else "US"
            p.is_premium = cell(r["Gói học"]).lower().startswith("có")
            p.premium_until = None
            p.avatar_frame = frame if frame in frames else ""
            p.onboarding_completed = True
            p.onboarding_completed_at = p.onboarding_completed_at or timezone.now()
            p.save()

            if frame in frames:
                UserCosmetic.objects.get_or_create(user=user, item=frames[frame])
            for code in re.split(r"[,\s]+", cell(r["Huy hiệu đạt được"])):
                if code in badges:
                    UserBadge.objects.get_or_create(user=user, badge=badges[code])
            xp_week = number(r["XP Tuần"])
            WeeklyStat.objects.update_or_create(
                user=user,
                iso_year=year,
                iso_week=week,
                defaults={"xp": xp_week, "days_active": min(streak, today.isoweekday())},
            )
            membership = ensure_league_membership(user)
            membership.xp_week = xp_week
            membership.save(update_fields=["xp_week"])
            n += 1
        self.log(
            f"Tài khoản: {n} tài khoản ({created} tạo mới) · {len(badges)} huy hiệu · "
            f"{len(frames)} khung · XP tuần {year}-W{week}"
        )

    def upload_avatar_from(self, user, url: str) -> str:
        """Ảnh ngoài (Unsplash…) → R2 `avatars/<id>.<ext>`, cùng chỗ với ảnh người dùng tự tải."""
        req = urllib.request.Request(
            url, headers={"Accept": "image/jpeg,image/png,image/webp", "User-Agent": "Sayfully"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            content_type = resp.headers.get_content_type()
            data = resp.read()
        ext = _AVATAR_TYPES.get(content_type)
        if ext is None:
            raise CommandError(f"Ảnh đại diện {url!r}: không nhận kiểu {content_type}")
        return upload_avatar(f"avatars/{user.id}.{ext}", data, content_type)
