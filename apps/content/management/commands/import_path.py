"""Nạp lộ trình A1→C1 (PATH-SCHEMA.md) từ thư mục crawl/ vào DB. Idempotent: upsert theo code / source_ref.

  python manage.py import_path                      # ../crawl cạnh Backend/
  python manage.py import_path --crawl-dir /path/to/crawl --purge   # xoá unit/bài/ngữ pháp/hội thoại demo trước
  python manage.py import_path --dry-run            # chạy trong transaction rồi rollback

Đọc: crawl/path/path.json (cây), generated_dialogues.json, generated_quiz_items.json, seed_*.csv,
     crawl/framework/framework_final.json, crawl/courses/courses_final.json, crawl/audio/audio_map.csv (đường dẫn mp3 R2).
Bước bài học sinh theo mẫu app hiện hỗ trợ: intro · vocab×8 · grammar · dialogue · spelling×2 · quiz×N.
(speak / pron / listen để dành tới khi app có màn tương ứng — dữ liệu đã nằm ở Lesson.*, QuizQuestion, PronunciationFeature.)
"""

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.content import models as m

POS_MAP = {
    "noun": "n",
    "verb": "v",
    "adjective": "adj",
    "adverb": "adv",
    "number": "num",
    "exclamation": "excl",
    "preposition": "prep",
    "pronoun": "pron",
    "conjunction": "conj",
    "determiner": "det",
    "modal verb": "modal",
    "auxiliary verb": "aux",
    "phrase": "phr",
    "phrasal verb": "v",
}
SUPER_VI = {
    "PRESENT": "Thì hiện tại",
    "PAST": "Thì quá khứ",
    "FUTURE": "Thì tương lai",
    "NOUNS": "Danh từ",
    "DETERMINERS": "Từ hạn định",
    "PRONOUNS": "Đại từ",
    "ADJECTIVES": "Tính từ",
    "ADVERBS": "Trạng từ",
    "PREPOSITIONS": "Giới từ",
    "QUESTIONS": "Câu hỏi",
    "NEGATION": "Phủ định",
    "VERBS": "Động từ",
    "MODALITY": "Động từ khuyết thiếu",
    "CONJUNCTIONS": "Liên từ",
    "CLAUSES": "Mệnh đề",
    "PASSIVES": "Bị động",
    "REPORTED SPEECH": "Câu tường thuật",
    "DISCOURSE MARKERS": "Từ nối diễn ngôn",
    "FOCUS": "Nhấn mạnh",
}
LEARNER_SPEAKERS = {"Linh", "Anna"}
csv.field_size_limit(10**7)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:64]


def app_level(label: str) -> str | None:
    return {
        "Pre-A1": "A1",
        "<A1": "A1",
        "A1": "A1",
        "A2": "A2",
        "A2+": "A2",
        "B1": "B1",
        "B1+": "B1",
        "B2": "B2",
        "B2+": "B2",
        "C1": "C1",
    }.get(label)


def _toks(t: str) -> list[str]:
    t = (t or "").lower().replace("’", "'").replace("—", " ").replace("…", " ")
    t = re.sub(r"\([^)]*\)", " ", t)  # (Mia)
    t = re.sub(r"^[a-z. ]{2,12}:\s", "", t)  # "Name: "
    return re.sub(r"[^a-z0-9' ]+", " ", t).split()


def match_line(text: str, lines: list) -> tuple:
    """Tìm lượt thoại chứa/khớp `text` (giải thích quiz = câu trong hội thoại). Trả (line, điểm 0–1)."""
    e = _toks(text)
    if not e:
        return None, 0.0
    best = (None, 0.0)
    for ln in lines:
        lt = _toks(ln["en"])
        if not lt:
            continue
        if " ".join(e) in " ".join(lt) or (" ".join(lt) in " ".join(e) and len(lt) >= 3):
            return ln, 1.0
        es, ls = set(e), set(lt)
        j = len(es & ls) / len(es | ls)
        if j > best[1]:
            best = (ln, j)
    return best


STOP = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "i",
    "am",
    "it",
    "to",
    "of",
    "and",
    "in",
    "she",
    "he",
    "says",
    "say",
    "that",
    "you",
    "my",
    "her",
    "his",
    "at",
}


def answer_matches(answer: str, sentence: str) -> bool:
    """Đáp án quiz có nói về đúng câu nghe không (Jaccard token, bỏ từ chức năng và 'Anna says,')."""
    a = set(_toks(re.sub(r"^[A-Za-z. ]{2,12} says,?\s*", "", answer or ""))) - STOP
    b = set(_toks(re.sub(r"^[A-Za-z. ]{2,12} says,?\s*", "", sentence or ""))) - STOP
    return bool(a and b) and len(a & b) / len(a | b) >= 0.3


VOCAB_Q = re.compile(r"^'([^']+)'")
MIN_LINE_SCORE = 0.25


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        first = f.readline()
        if not first.startswith("#"):
            f.seek(0)
        return list(csv.DictReader(f))


class Command(BaseCommand):
    help = "Nạp lộ trình (bands, can-do, chức năng, phát âm, ngữ pháp, từ vựng, bài, hội thoại, quiz, bước) từ crawl/."

    def add_arguments(self, parser):
        parser.add_argument(
            "--crawl-dir", default=str(Path(__file__).resolve().parents[5] / "crawl")
        )
        parser.add_argument(
            "--purge",
            action="store_true",
            help="Xoá Unit/Lesson/GrammarPoint/Dialogue hiện có trước khi nạp.",
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--skip-vocab", action="store_true", help="Bỏ qua từ vựng (nhanh khi chỉ sửa bài)."
        )

    # ------------------------------------------------------------------ helpers
    def log(self, msg):
        self.stdout.write(msg)

    def load(self, crawl: Path):
        self.P = json.load(open(crawl / "path" / "path.json", encoding="utf-8"))
        self.F = json.load(open(crawl / "framework" / "framework_final.json", encoding="utf-8"))
        self.C = json.load(open(crawl / "courses" / "courses_final.json", encoding="utf-8"))
        self.GEN = {
            "gen:" + d["lesson"]: d
            for d in json.load(open(crawl / "path" / "generated_dialogues.json", encoding="utf-8"))[
                "dialogues"
            ]
        }
        self.GENQ = {
            q["id"]: q
            for q in json.load(
                open(crawl / "path" / "generated_quiz_items.json", encoding="utf-8")
            )["items"]
        }
        self.EV = {v["id"]: v for v in self.F["vocabulary"]["evp"]}
        self.VD, self.VQ, self.VL = {}, {}, {}
        for _, book in self.C["voa"].items():
            for u in book["units"]:
                for d in u["dialogues"]:
                    self.VD[d["id"]] = d
                for q in u["quizzes"]:
                    self.VQ[q["id"]] = q
                for s_ in u["listening_sentences"]:
                    self.VL[s_["id"]] = s_
        self.AUDIO, self.AUDIO_KEYS = {}, set()
        am = crawl / "audio" / "audio_map.csv"
        if am.exists():
            for r in read_csv(am):
                self.AUDIO[r["ref"]] = (
                    r["key_us"] if r["done_us"] else "",
                    r["key_uk"] if r["done_uk"] else "",
                )
                self.AUDIO_KEYS.update(k for k in (self.AUDIO[r["ref"]]) if k)
        self.crawl = crawl

    def audio(self, ref: str, headword: str | None = None) -> dict:
        us, uk = self.AUDIO.get(ref, ("", ""))
        if headword and not (
            us or uk
        ):  # từ nhiều nghĩa dùng chung 1 file audio/<accent>/<headword>.mp3
            k = re.sub(r"[^a-z0-9.\-]+", "_", headword.lower()).strip("_")
            us = f"audio/us/{k}.mp3" if f"audio/us/{k}.mp3" in self.AUDIO_KEYS else ""
            uk = f"audio/uk/{k}.mp3" if f"audio/uk/{k}.mp3" in self.AUDIO_KEYS else ""
        return {"audio_us_path": us, "audio_uk_path": uk}

    # ------------------------------------------------------------------ main
    def handle(self, *args, **opts):
        crawl = Path(opts["crawl_dir"]).resolve()
        if not (crawl / "path" / "path.json").exists():
            raise CommandError(f"Không thấy {crawl}/path/path.json")
        self.load(crawl)
        with transaction.atomic():
            if opts["purge"]:
                self.purge()
            self.sources()
            self.bands()
            self.can_dos()
            self.band_goals()
            self.functions()
            self.pron_features()
            self.grammar()
            if not opts["skip_vocab"]:
                self.vocabulary()
            self.units()
            self.lessons()
            self.summary()
            if opts["dry_run"]:
                transaction.set_rollback(True)
                self.log(self.style.WARNING("[DRY-RUN] đã rollback."))
            else:
                self.log(self.style.SUCCESS("Nạp lộ trình xong."))

    def purge(self):
        n = (
            m.Unit.objects.count(),
            m.Lesson.objects.count(),
            m.GrammarPoint.objects.count(),
            m.Dialogue.objects.count(),
        )
        m.LessonStep.objects.all().delete()
        m.Unit.objects.all().delete()  # cascade Lesson → objectives, quiz, dialogues(lesson)
        m.Dialogue.objects.all().delete()
        m.GrammarPoint.objects.all().delete()
        self.log(f"purge: xoá unit {n[0]}, bài {n[1]}, ngữ pháp {n[2]}, hội thoại {n[3]}")

    # ------------------------------------------------------------------ 1. khung
    def sources(self):
        src = self.F["sources"]
        items = src.items() if isinstance(src, dict) else [(x["code"], x) for x in src]
        for code, v in items:
            m.ContentSource.objects.update_or_create(
                code=code,
                defaults={
                    "name": v.get("name", "")[:200],
                    "license": v.get("license", "") or "",
                    "usage": v.get("usage", "") or "",
                    "attribution": (v.get("attribution") or "")[:512],
                    "tos_note": v.get("tos_note") or v.get("note") or "",
                },
            )
        self.log(f"ContentSource: {len(items)}")

    def bands(self):
        self.BAND = {}
        for b in self.P["bands"]:
            lv = m.Level.objects.get(code=b["level"])
            ms, _ = m.LevelMilestone.objects.update_or_create(
                level=lv,
                order=b["order"],
                defaults={
                    "code": f"{b['level'].lower()}-{b['order']}",
                    "name": b["code"],
                    "title_vi": f"Chứng chỉ {b['code']}",
                    "requirement_lessons": 36,
                    "reward_xp": 300,
                    "reward_coins": 150,
                },
            )
            band, _ = m.Band.objects.update_or_create(
                code=b["code"],
                defaults={
                    "level": lv,
                    "order": b["order"],
                    "cefr_label": b["cefr_label"],
                    "gse_min": b["gse_min"],
                    "gse_max": b["gse_max"],
                    "title_vi": b["title_vi"],
                    "milestone": ms,
                },
            )
            self.BAND[b["code"]] = band
        self.log(f"Band: {len(self.BAND)} (+ LevelMilestone)")

    def can_dos(self):
        rows = read_csv(self.crawl / "path" / "seed_can_dos.csv")
        existing = {c.code: c for c in m.CanDo.objects.all()}
        create, update = [], []
        for r in rows:
            ex_en = [x.strip() for x in (r.get("examples_en") or "").split(" | ") if x.strip()]
            ex_vi = [x.strip() for x in (r.get("examples_vi") or "").split(" | ") if x.strip()]
            vals = dict(
                source=r["source"],
                level_id=r["level"],
                cefr_label=r["cefr_label"],
                gse=int(r["gse"]) if r.get("gse") else None,
                skill=(r.get("skill") or "")[:128],
                scale=(r.get("scale") or "")[:255],
                can_do_vi=r["can_do_vi"][:512],
                can_do_en=r["can_do_en"][:512],
                examples=[{"en": a, "vi": b} for a, b in zip(ex_en, ex_vi, strict=False)],
                is_speaking_core=bool((r.get("is_speaking_core") or "").strip()),
            )
            if r["code"] in existing:
                obj = existing[r["code"]]
                for k, v in vals.items():
                    setattr(obj, k, v)
                update.append(obj)
            else:
                create.append(m.CanDo(code=r["code"], **vals))
        m.CanDo.objects.bulk_create(create, batch_size=500)
        m.CanDo.objects.bulk_update(update, list(vals.keys()), batch_size=500)
        self.CANDO = {c.code: c for c in m.CanDo.objects.all()}
        self.log(f"CanDo: +{len(create)} ~{len(update)} (tổng {len(self.CANDO)})")

    def band_goals(self):
        rows = read_csv(self.crawl / "path" / "seed_band_goals.csv")
        m.BandGoal.objects.all().delete()
        m.BandGoal.objects.bulk_create(
            [
                m.BandGoal(
                    band=self.BAND[r["band"]],
                    can_do=self.CANDO[r["can_do_code"]],
                    order=int(r["order"]),
                )
                for r in rows
                if r["can_do_code"] in self.CANDO
            ]
        )
        self.log(f"BandGoal: {m.BandGoal.objects.count()}")

    def functions(self):
        self.FUNC = {}
        for r in read_csv(self.crawl / "path" / "seed_functions.csv"):
            f, _ = m.LanguageFunction.objects.update_or_create(
                number=int(r["number"]),
                defaults={
                    "title_en": r["title_en"][:160],
                    "title_vi": (r.get("title_vi") or "")[:160],
                },
            )
            self.FUNC[f.number] = f
        n = 0
        for r in read_csv(self.crawl / "path" / "seed_exponents.csv"):
            f = self.FUNC.get(int(r["function_number"]))
            if not f:
                continue
            ex_en = [x.strip() for x in (r.get("examples_en") or "").split(" | ") if x.strip()]
            ex_vi = [x.strip() for x in (r.get("examples_vi") or "").split(" | ") if x.strip()]
            m.FunctionExponent.objects.update_or_create(
                function=f,
                level_id=r["level"],
                defaults={
                    "title_en": r["title_en"][:160],
                    "examples": [{"en": a, "vi": b} for a, b in zip(ex_en, ex_vi, strict=False)],
                },
            )
            n += 1
        self.log(f"LanguageFunction: {len(self.FUNC)} · FunctionExponent: {n}")

    def pron_features(self):
        self.PRON = {}
        sounds = list(m.IPASound.objects.all())
        for i, r in enumerate(read_csv(self.crawl / "path" / "seed_pron_features.csv"), 1):
            f, _ = m.PronunciationFeature.objects.update_or_create(
                code=r["id"],
                defaults={
                    "category_en": r["category"][:64],
                    "category_vi": r["category_vi"][:64],
                    "feature_en": r["feature"][:160],
                    "status": r["status"][:10],
                    "ipa": (r.get("ipa") or "")[:96],
                    "rule_en": r.get("rule_en") or "",
                    "rule_vi": r["rule_vi"],
                    "focus_en": r.get("pedagogical_focus_en") or "",
                    "focus_vi": r.get("pedagogical_focus_vi") or "",
                    "examples_en": r.get("examples_en") or "",
                    "examples_vi": r.get("examples_vi") or "",
                    "order": i,
                },
            )
            ipa = r.get("ipa") or ""
            f.sounds.set([s_ for s_ in sounds if s_.symbol and s_.symbol in ipa])
            self.PRON[f.code] = f
        self.log(f"PronunciationFeature: {len(self.PRON)}")

    # ------------------------------------------------------------------ 2. ngữ pháp
    def grammar(self):
        core = {str(L["grammar_point"]) for L in self.P["lessons"] if L["grammar_point"]}
        gobj = defaultdict(set)
        for L in self.P["lessons"]:
            if L["grammar_point"]:
                gobj[str(L["grammar_point"])].update(L["grammar_objectives"])
        existing = {g.source_ref: g for g in m.GrammarPoint.objects.exclude(source_ref="")}
        used_orders = defaultdict(set)
        for g in m.GrammarPoint.objects.all():
            used_orders[g.level_id].add(g.order)
        counter = defaultdict(int)
        self.GP = {}
        n_new = 0
        for g in self.F["grammar_points"]:
            ref = str(g["id"])
            lv = g["level"]
            ex = g.get("examples") or []
            vals = dict(
                level_id=lv,
                category=SUPER_VI.get(g["super_category"], g["super_category"].title())[:48],
                title_vi=g["title_vi"][:160],
                title_en=(g.get("guideword") or "")[:160],
                subtitle_vi=(g.get("sub_category") or "")[:160],
                formula=(g.get("formula") or "")[:160],
                explanation_vi=g.get("explanation_vi") or "",
                source_ref=ref,
                super_category=g["super_category"][:32],
                sub_category=(g.get("sub_category") or "")[:96],
                guideword_type=(g.get("guideword_type") or "")[:10],
                guideword=(g.get("guideword") or "")[:200],
                lexical_range=(g.get("lexical_range") or "")[:32],
                is_path_core=ref in core,
            )
            obj = existing.get(ref)
            if obj:
                for k, v in vals.items():
                    setattr(obj, k, v)
                obj.save()
            else:
                counter[lv] += 1
                while counter[lv] in used_orders[lv]:
                    counter[lv] += 1
                used_orders[lv].add(counter[lv])
                obj = m.GrammarPoint.objects.create(order=counter[lv], **vals)
                n_new += 1
            obj.examples.all().delete()
            m.GrammarExample.objects.bulk_create(
                [
                    m.GrammarExample(
                        grammar_point=obj,
                        order=i,
                        text_en=e["en"][:255],
                        text_vi=e["vi"][:255],
                        **self.audio(f"{ref}#{i}"),
                    )
                    for i, e in enumerate(ex, 1)
                ]
            )
            if gobj.get(ref):
                obj.objectives.set([self.CANDO[c] for c in gobj[ref] if c in self.CANDO])
            self.GP[ref] = obj
        self.log(
            f"GrammarPoint: {len(self.GP)} (+{n_new} mới; lõi lộ trình {len(core)}) · GrammarExample: {m.GrammarExample.objects.count()}"
        )

    # ------------------------------------------------------------------ 3. từ vựng (chỉ sense trong lộ trình)
    def vocabulary(self):
        ids = []
        seen = set()
        for L in self.P["lessons"]:
            for v in L["vocabulary"]:
                if v not in seen:
                    seen.add(v)
                    ids.append(v)
        src_evp = m.ContentSource.objects.filter(code="evp").first()
        topics = {t.code: t for t in m.Topic.objects.all()}
        by_ref = {v.source_ref: v for v in m.Vocabulary.objects.exclude(source_ref="")}
        self.VOCAB = {}
        n_new = n_adopt = 0
        for vid in ids:
            e = self.EV[vid]
            pos = POS_MAP.get(e["pos"], "n")
            sense = slug(e.get("guideword") or "") if e.get("guideword") else ""
            vals = dict(
                level_id=e["level"],
                meaning_vi=e["meaning_vi"][:255],
                definition_en=e.get("definition_en") or "",
                ipa_uk=(e.get("ipa_uk") or "")[:64],
                ipa_us=(e.get("ipa_us") or "")[:64],
                sense=sense,
                sense_label_en=(e.get("guideword") or "")[:96],
                headword_us=(e.get("headword_us") or "")[:64],
                category="phrasal_verb" if e["pos"] == "phrasal verb" else "word",
                usage_label=(e.get("usage") or "")[:32],
                source=src_evp,
                source_ref=vid,
                is_path_core=True,
                **self.audio(vid, e["headword"]),
            )
            obj = by_ref.get(vid)
            if not obj:
                obj = m.Vocabulary.objects.filter(
                    headword=e["headword"], pos=pos, sense=sense
                ).first()
                if not obj and sense:  # bản ghi demo cũ chưa có sense → nhận lại
                    obj = m.Vocabulary.objects.filter(
                        headword=e["headword"], pos=pos, sense="", source_ref=""
                    ).first()
                    if obj:
                        n_adopt += 1
            if obj:
                for k, v in vals.items():
                    setattr(obj, k, v)
                obj.save()
            else:
                obj = m.Vocabulary.objects.create(headword=e["headword"][:64], pos=pos, **vals)
                n_new += 1
            obj.examples.all().delete()
            m.VocabularyExample.objects.bulk_create(
                [
                    m.VocabularyExample(
                        vocabulary=obj,
                        order=i,
                        text_en=x["en"][:255],
                        text_vi=x["vi"][:255],
                        **self.audio(f"{vid}#{i}"),
                    )
                    for i, x in enumerate(e.get("examples") or [], 1)
                ]
            )
            tps = [t.strip() for t in (e.get("topics") or "").split("|") if t.strip()]
            if tps:
                objs = []
                for t in tps:
                    code = slug(t)
                    if code not in topics:
                        topics[code] = m.Topic.objects.create(
                            code=code, name_vi=t[:64], name_en=t[:64], order=len(topics) + 1
                        )
                    objs.append(topics[code])
                obj.topics.set(objs)
            self.VOCAB[vid] = obj
        stale = (
            m.Vocabulary.objects.filter(is_path_core=True)
            .exclude(source_ref__in=ids)
            .update(is_path_core=False)
        )  # từ bị thay khỏi lộ trình → về từ điển
        self.log(
            f"Vocabulary (lộ trình): {len(self.VOCAB)} (bỏ khỏi lộ trình {stale}) (+{n_new} mới, {n_adopt} nhận lại demo) · VocabularyExample: {m.VocabularyExample.objects.filter(vocabulary__is_path_core=True).count()}"
        )

    # ------------------------------------------------------------------ 4. unit / bài
    def units(self):
        fn_by_code = {r["code"]: r for r in read_csv(self.crawl / "path" / "seed_units.csv")}
        lesson_gse = defaultdict(list)
        for L in self.P["lessons"]:
            if L["gse"]:
                lesson_gse[L["unit"]].append(L["gse"])
        self.UNIT = {}
        for u in self.P["units"]:
            r = fn_by_code.get(u["code"], {})
            fnum = int(r["function_number"]) if r.get("function_number") else None
            g = lesson_gse.get(u["code"], [])
            obj = (
                m.Unit.objects.filter(code=u["code"]).first()
                or m.Unit.objects.filter(level_id=u["level"], order=u["order"]).first()
            )
            vals = dict(
                level_id=u["level"],
                order=u["order"],
                code=u["code"],
                title_vi=u["title_vi"][:128],
                title_en=u["title_en"][:128],
                subtitle=(u.get("function") or "")[:128],
                description_vi=(u.get("function_vi") or "")[:255],
                band=self.BAND.get(u["band"]),
                function=self.FUNC.get(fnum) if fnum else None,
                topic_en=(u.get("topic") or "")[:64],
                topic_vi=(u.get("topic_vi") or "")[:64],
                gse_min=min(g) if g else None,
                gse_max=max(g) if g else None,
            )
            if obj:
                for k, v in vals.items():
                    setattr(obj, k, v)
                obj.save()
            else:
                obj = m.Unit.objects.create(**vals)
            self.UNIT[u["code"]] = obj
        self.log(f"Unit: {len(self.UNIT)}")

    def lessons(self):
        n_dlg = n_line = n_quiz = n_step = 0
        vocab_by_ref = getattr(self, "VOCAB", None) or {
            v.source_ref: v for v in m.Vocabulary.objects.exclude(source_ref="")
        }
        for L in self.P["lessons"]:
            objs = [(self.CANDO.get(o["code"]), o["is_primary"]) for o in L["objectives"]]
            primary = next((c for c, p in objs if p and c), next((c for c, _ in objs if c), None))
            vals = dict(
                unit=self.UNIT[L["unit"]],
                order=L["order"],
                title_vi=L["title_vi"][:128],
                title_en=L["title_en"][:128],
                description_vi=" · ".join(c.can_do_vi for c, _ in objs if c),
                path_subtitle_vi=(primary.can_do_vi if primary else "")[:160],
                est_minutes=L["est_minutes"],
                xp_reward=L["xp_reward"],
                grammar_point=self.GP.get(str(L["grammar_point"])) if L["grammar_point"] else None,
                pronunciation_feature=self.PRON.get(L["pronunciation_feature"]),
                speaking_function=self.FUNC.get(L["speaking_function"])
                if L["speaking_function"]
                else None,
                gse=L["gse"],
                source_ref=(L["source_ref"] or "")[:32],
            )
            lesson, _ = m.Lesson.objects.update_or_create(code=L["code"], defaults=vals)
            # objectives
            lesson.objectives.all().delete()
            m.LessonObjective.objects.bulk_create(
                [
                    m.LessonObjective(lesson=lesson, can_do=c, order=i, is_primary=p)
                    for i, (c, p) in enumerate(objs, 1)
                    if c
                ]
            )
            # dialogue
            did = L["dialogue"]
            src = self.GEN.get(did) or self.VD.get(did)
            dialogue = None
            if src:
                dialogue, _ = m.Dialogue.objects.update_or_create(
                    source_ref=did,
                    defaults={
                        "lesson": lesson,
                        "title_en": (src.get("title_en") or L["title_en"])[:128],
                        "title_vi": (src.get("title_vi") or "")[:128],
                        "context_en": (src.get("context_en") or "")[:255],
                    },
                )
                dialogue.lines.all().delete()
                m.DialogueLine.objects.bulk_create(
                    [
                        m.DialogueLine(
                            dialogue=dialogue,
                            order=ln["n"],
                            speaker=ln["speaker"][:32],
                            is_native=ln["speaker"] not in LEARNER_SPEAKERS,
                            text_en=ln["en"][:1024],
                            text_vi=(ln.get("vi") or "")[:1024],
                            **self.audio(f"{did}#{ln['n']}"),
                        )
                        for ln in src["lines"]
                    ]
                )
                n_dlg += 1
                n_line += len(src["lines"])
            # quiz bank
            lesson.quiz_questions.all().delete()
            qs = []
            # VOA: quiz là bài nghe "What does Anna say?" — câu nghe thứ i (listening_sentences[i]) là audio phát trước câu hỏi i
            voa_listen = [
                self.VL.get(sid) for sid in L["listening_sentences"]
            ]  # câu nghe i ↔ quiz i chỉ khi đáp án khớp nội dung
            dlines = src["lines"] if src else []
            self.quiz_line = getattr(self, "quiz_line", {})
            for i, qid in enumerate(L["quiz_questions"], 1):
                if qid in self.GENQ:
                    q = self.GENQ[qid]
                    aud = {}
                    if q.get("audio_ref"):  # build_quiz.py đã chốt nguồn audio (thoại/ví dụ)
                        aud = self.audio(q["audio_ref"])
                    elif (
                        q["kind"] == "listening"
                    ):  # giải thích = câu trong hội thoại → phát audio lượt đó (bài nghe thật)
                        ln, sc = match_line(q.get("explanation_vi", ""), dlines)
                        if ln and sc >= MIN_LINE_SCORE:
                            aud = self.audio(f"{did}#{ln['n']}")
                            self.quiz_line[qid] = ln["n"]
                    qs.append(
                        m.QuizQuestion(
                            lesson=lesson,
                            order=i,
                            kind=q["kind"],
                            question_en=q["question_en"][:512],
                            question_vi=q["question_vi"][:512],
                            options=q["options"],
                            answer_index=max(q["answer_index"], 0),
                            explanation_vi=q.get("explanation_vi", "")[:512],
                            sentence_en=q.get("sentence_en", "")[:512],
                            sentence_vi=q.get("sentence_vi", "")[:512],
                            speaker=q.get("speaker", "")[:32],
                            hint_vi=q.get("hint_vi", "")[:256],
                            formula=q.get("formula", "")[:128],
                            source_ref=qid,
                            **aud,
                        )
                    )
                elif qid in self.VQ:
                    q = self.VQ[qid]
                    opts = [o["text"] for o in q["options"]]
                    keys = [o["key"] for o in q["options"]]
                    if q["answer_key"] not in keys:
                        continue
                    ans = opts[keys.index(q["answer_key"])]
                    ls = voa_listen[i - 1] if i - 1 < len(voa_listen) else None
                    aud = {}
                    if ls and answer_matches(ans, ls["en"]):  # bài nghe VOA: phát câu nghe rồi hỏi
                        aud = self.audio(ls["id"])
                        self.quiz_heard = getattr(self, "quiz_heard", {})
                        self.quiz_heard[qid] = ls["en"]
                    else:  # đọc-hiểu hội thoại → phát lượt thoại chứa đáp án nếu khớp
                        ln, sc = match_line(ans, dlines)
                        if ln and sc >= 0.5:
                            aud = self.audio(f"{did}#{ln['n']}")
                            self.quiz_line[qid] = ln["n"]
                    qs.append(
                        m.QuizQuestion(
                            lesson=lesson,
                            order=i,
                            kind="listening",
                            question_en=q["question_en"][:512],
                            question_vi=(q.get("question_vi") or "")[:512],
                            options=opts,
                            answer_index=keys.index(q["answer_key"]),
                            source_ref=qid,
                            **aud,
                        )
                    )
            m.QuizQuestion.objects.bulk_create(qs)
            n_quiz += len(qs)
            # steps
            n_step += self.build_steps(lesson, L, dialogue, qs, vocab_by_ref, primary)
        self.log(
            f"Lesson: {len(self.P['lessons'])} · LessonObjective: {m.LessonObjective.objects.count()} · Dialogue: {n_dlg} ({n_line} lượt) · QuizQuestion: {n_quiz} · LessonStep: {n_step}"
        )

    def build_steps(self, lesson, L, dialogue, qs, vocab_by_ref, primary) -> int:
        K = m.LessonStep.Kind
        lesson.steps.all().delete()
        steps = []
        vocabs = [vocab_by_ref[v] for v in L["vocabulary"] if v in vocab_by_ref]
        preview = [
            {
                "text_en": ln.text_en,
                "text_vi": ln.text_vi,
                "audio_us_path": ln.audio_us_path,
                "audio_uk_path": ln.audio_uk_path,
            }
            for ln in (dialogue.lines.order_by("order")[:2] if dialogue else [])
        ]
        steps.append(
            m.LessonStep(
                lesson=lesson,
                order=1,
                kind=K.INTRO,
                payload={
                    "highlight_vi": primary.can_do_vi if primary else lesson.title_vi,
                    "preview": preview,
                },
            )
        )
        for v in vocabs:
            steps.append(
                m.LessonStep(lesson=lesson, order=len(steps) + 1, kind=K.VOCAB, vocabulary=v)
            )
        if lesson.grammar_point_id:
            steps.append(
                m.LessonStep(
                    lesson=lesson,
                    order=len(steps) + 1,
                    kind=K.GRAMMAR,
                    grammar_point=lesson.grammar_point,
                )
            )
        if dialogue:
            steps.append(
                m.LessonStep(
                    lesson=lesson, order=len(steps) + 1, kind=K.DIALOGUE, dialogue=dialogue
                )
            )
        for v in vocabs[:2]:
            steps.append(
                m.LessonStep(
                    lesson=lesson,
                    order=len(steps) + 1,
                    kind=K.SPELLING,
                    vocabulary=v,
                    payload={"hint_vi": v.meaning_vi},
                )
            )
        by_head = {v.headword.lower(): v for v in vocabs}
        for q in qs:
            vq = None
            if (
                q.kind == "vocab"
            ):  # "'Argue' means:" → màn quiz từ vựng của app: từ to + IPA + loa, chọn nghĩa VI
                mm = VOCAB_Q.match(q.question_en)
                vq = by_head.get(mm.group(1).lower()) if mm else None
            prompt = {  # nhãn nhỏ đầu màn (app hiện in hoa); mỗi kind một màn riêng
                "vocab": "Nghĩa của từ này là gì?",
                "cloze": "Nghe và điền từ còn thiếu",
                "reorder": "Sắp xếp thành câu đúng",
                "grammar": "Chọn câu đúng ngữ pháp",
                "listening": "Nghe rồi trả lời",
            }.get(q.kind, q.question_vi or "Chọn đáp án đúng")
            steps.append(
                m.LessonStep(
                    lesson=lesson,
                    order=len(steps) + 1,
                    kind=K.QUIZ,
                    vocabulary=vq,
                    payload={
                        "question_id": q.id,
                        "kind": q.kind,
                        "prompt_vi": prompt,
                        "question_word": q.question_en,
                        "question_vi": q.question_vi,
                        "source_line": self.quiz_line.get(q.source_ref),
                        "audio_text": q.sentence_en
                        or getattr(self, "quiz_heard", {}).get(q.source_ref, ""),
                        "sentence_en": q.sentence_en,
                        "sentence_vi": q.sentence_vi,
                        "speaker": q.speaker,
                        "hint_vi": q.hint_vi,
                        "formula": q.formula,
                        "options": q.options,
                        "correct_index": q.answer_index,
                        "explanation_vi": q.explanation_vi,
                        "audio_us_path": q.audio_us_path,
                        "audio_uk_path": q.audio_uk_path,
                        "xp": 10,
                    },
                )
            )
        m.LessonStep.objects.bulk_create(steps)
        return len(steps)

    def summary(self):
        self.log("--- DB sau khi nạp ---")
        for M in (
            m.Band,
            m.CanDo,
            m.BandGoal,
            m.LanguageFunction,
            m.FunctionExponent,
            m.PronunciationFeature,
            m.GrammarPoint,
            m.GrammarExample,
            m.Vocabulary,
            m.VocabularyExample,
            m.Unit,
            m.Lesson,
            m.LessonObjective,
            m.Dialogue,
            m.DialogueLine,
            m.QuizQuestion,
            m.LessonStep,
        ):
            self.log(f"  {M.__name__:22s} {M.objects.count()}")
        self.log(
            f"  {'…vocab có audio US':22s} {m.Vocabulary.objects.filter(is_path_core=True).exclude(audio_us_path='').count()}"
        )
        self.log(
            f"  {'…lượt thoại có audio US':22s} {m.DialogueLine.objects.exclude(audio_us_path='').count()}"
        )
