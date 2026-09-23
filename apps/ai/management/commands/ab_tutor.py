"""So sánh nhiều model qua ĐÚNG prompt production của Gia sư AI (services._ask).

Mỗi model chạy cùng một kịch bản lượt nói của người học rồi thu: JSON hợp lệ, có `reply_vi`
(A1/A2), có `correction`, số token, độ trễ, chi phí ước tính. Tuỳ chọn `--judge` dùng một model
làm giám khảo chấm độ tự nhiên tiếng Việt + độ khớp CEFR để chọn primary.

Ví dụ:
    export OPENROUTER_API_KEY=sk-or-...
    python manage.py ab_tutor \
        --models deepseek/deepseek-v4.1-flash,openai/gpt-6-luna \
        --cefr A2 --turns 6 --judge openai/gpt-6-luna
    python manage.py ab_tutor --models mock        # tự kiểm tra, không cần key
"""

from __future__ import annotations

import json
import os
import statistics
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.accounts.services import ensure_profile
from apps.ai import llm
from apps.ai import services as svc
from apps.ai.models import AIConversation

# Giá OpenRouter ($/1M token in, out) để ước chi phí — bổ sung khi cần, thiếu thì bỏ qua cột chi phí.
PRICES = {
    "deepseek/deepseek-v4.1-flash": (0.06, 0.32),
    "deepseek/deepseek-v4-flash": (0.089, 0.177),
    "openai/gpt-6-luna": (0.10, 0.50),
    "openai/gpt-6-luna:batch": (0.05, 0.25),
}

# Lượt nói cố định cho mọi model (cùng đầu vào để so công bằng); vài câu cài lỗi để kiểm tra `correction`.
SCRIPT = [
    "Hi Long! Last summer I go to Da Nang with my family.",
    "We stay there five day and swim every morning.",
    "The food was amazing, I eat seafood every night.",
    "My favourite place is the Marble Mountains.",
    "Next year I want visit Ha Long Bay.",
    "Do you have any tips for me?",
    "Thank you! I will practice more.",
    "See you tomorrow!",
]

REQUIRED_KEYS = {
    "reply_en",
    "reply_vi",
    "correction",
    "vocab",
    "praise_vi",
    "suggested_replies",
    "goals_completed",
    "on_topic",
    "suggested_end",
}


class Command(BaseCommand):
    help = "So sánh model cho Gia sư AI qua prompt production; tuỳ chọn chấm bằng model giám khảo."

    def add_arguments(self, parser):
        parser.add_argument("--models", required=True, help="Danh sách model, phân tách bằng dấu phẩy")
        parser.add_argument("--cefr", default="A2", help="Trình độ người học (mặc định A2)")
        parser.add_argument("--topic", default="random", help="Mã chủ đề free-talk (mặc định random)")
        parser.add_argument("--turns", type=int, default=6, help="Số lượt (tối đa %d)" % len(SCRIPT))
        parser.add_argument("--judge", default="", help="Model giám khảo (trống = bỏ qua)")
        parser.add_argument("--key", default="", help="OpenRouter key (mặc định lấy từ env)")
        parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")

    def handle(self, *args, **opts):
        models = [m.strip() for m in opts["models"].split(",") if m.strip()]
        turns = max(1, min(opts["turns"], len(SCRIPT)))
        key = opts["key"] or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("AI_API_KEY", "")
        if any(m != "mock" for m in models) and not key:
            raise CommandError("Thiếu key: đặt OPENROUTER_API_KEY hoặc dùng --key (hoặc --models mock).")

        topic = (svc._topic(opts["topic"]) or svc._topic("random"))["code"]
        user, created = User.objects.get_or_create(
            email="__ab_tutor__@sayfully.dev", defaults={"full_name": "AB Tutor"}
        )
        profile = ensure_profile(user)
        profile.cefr_level = opts["cefr"]
        profile.save(update_fields=["cefr_level"])
        conv = AIConversation.objects.create(
            user=user, kind=AIConversation.Kind.TUTOR, topic=topic, title_vi="AB", use_notebook=False
        )
        saved = {k: getattr(settings, k) for k in ("AI_PROVIDER", "AI_BASE_URL", "AI_MODEL", "AI_FALLBACK_MODEL", "AI_API_KEY")}
        try:
            runs = {m: self._run_model(m, profile, conv, turns, key, opts["base_url"]) for m in models}
            self._report(runs, turns, opts["cefr"])
            if opts["judge"]:
                self._judge(runs, models, turns, opts["judge"], key, opts["base_url"])
        finally:
            for k, v in saved.items():
                setattr(settings, k, v)
            conv.delete()
            if created:
                user.delete()

    def _apply(self, model: str, key: str, base_url: str):
        if model == "mock":
            settings.AI_PROVIDER = "mock"
            return
        settings.AI_PROVIDER = "openai_compat"
        settings.AI_BASE_URL = base_url
        settings.AI_MODEL = model
        settings.AI_FALLBACK_MODEL = ""
        settings.AI_API_KEY = key

    def _run_model(self, model, profile, conv, turns, key, base_url):
        self._apply(model, key, base_url)
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n▶ {model}"))
        history: list[dict] = []
        rows: list[dict] = []
        for i in range(turns):
            history.append({"role": "user", "content": SCRIPT[i]})
            started = time.monotonic()
            try:
                data, comp = svc._ask(profile, conv, history)
            except llm.AIUpstreamError as exc:
                rows.append({"ok": False, "error": str(exc)})
                self.stdout.write(self.style.ERROR(f"  lượt {i + 1}: LỖI {exc}"))
                break
            latency = int((time.monotonic() - started) * 1000)
            history.append({"role": "assistant", "content": data["reply_en"]})
            rows.append(
                {
                    "ok": True,
                    "data": data,
                    "keys_ok": REQUIRED_KEYS.issubset(data.keys()),
                    "has_vi": bool(data.get("reply_vi")),
                    "has_corr": data.get("correction") is not None,
                    "tokens_in": comp.tokens_in,
                    "tokens_out": comp.tokens_out,
                    "latency": latency,
                }
            )
            self.stdout.write(f"  lượt {i + 1}: {data['reply_en']}")
            if data.get("correction"):
                self.stdout.write(self.style.WARNING(f"    ✎ {data['correction'].get('note_vi')}"))
            if data.get("reply_vi"):
                self.stdout.write(f"    vi: {data['reply_vi']}")
        return rows

    def _report(self, runs, turns, cefr):
        vi_expected = cefr in ("A1", "A2")
        self.stdout.write(self.style.MIGRATE_HEADING("\n=== TỔNG HỢP ==="))
        header = f"{'model':<34} {'ok':>5} {'json':>5} {'vi':>5} {'corr':>5} {'tok_in':>7} {'tok_out':>8} {'p50ms':>7} {'$/1k':>8}"
        self.stdout.write(header)
        for model, rows in runs.items():
            ok = [r for r in rows if r.get("ok")]
            if not ok:
                self.stdout.write(f"{model:<34} {'0/%d' % turns:>5}  (tất cả lượt lỗi)")
                continue
            lat = [r["latency"] for r in ok]
            tin = statistics.mean(r["tokens_in"] for r in ok)
            tout = statistics.mean(r["tokens_out"] for r in ok)
            price = PRICES.get(model)
            cost = f"${(tin * price[0] + tout * price[1]) / 1e6 * 1000:.3f}" if price else "-"
            vi = sum(r["has_vi"] for r in ok)
            self.stdout.write(
                f"{model:<34} {len(ok):>3}/{turns} "
                f"{sum(r['keys_ok'] for r in ok):>4}/{len(ok)} "
                f"{vi:>4}/{len(ok)} "
                f"{sum(r['has_corr'] for r in ok):>4}/{len(ok)} "
                f"{tin:>7.0f} {tout:>8.0f} {int(statistics.median(lat)):>7} {cost:>8}"
            )
        note = "reply_vi mong đợi CÓ (A1/A2)" if vi_expected else "reply_vi mong đợi TRỐNG (>A2)"
        self.stdout.write(self.style.HTTP_INFO(f"\nCEFR={cefr}: {note}. Cột json = số lượt đủ 8 khoá."))

    def _judge(self, runs, models, turns, judge_model, key, base_url):
        self._apply(judge_model, key, base_url)
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== GIÁM KHẢO ({judge_model}) ==="))
        wins = {m: 0 for m in models}
        nat = {m: [] for m in models}
        for i in range(turns):
            entries = {}
            for m in models:
                rows = runs[m]
                if i < len(rows) and rows[i].get("ok"):
                    d = rows[i]["data"]
                    entries[m] = {"reply_en": d["reply_en"], "note_vi": (d.get("correction") or {}).get("note_vi"), "reply_vi": d.get("reply_vi")}
            if len(entries) < 2:
                continue
            system = (
                "Bạn chấm chất lượng phản hồi của gia sư tiếng Anh cho người học Việt. Chấm mỗi model: "
                "naturalness_vi (1-5, tiếng Việt tự nhiên như người bản xứ) và cefr_fit (1-5, hợp trình độ). "
                'Trả về DUY NHẤT JSON: {"scores":{"<model>":{"naturalness_vi":n,"cefr_fit":n}},"winner":"<model>"}.'
            )
            payload = {"learner": SCRIPT[i], "candidates": entries}
            try:
                # Judge cần trần token rộng: model có reasoning (vd gemini) dễ bị cắt JSON ở mức thấp.
                comp = llm.complete(system, [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], max_tokens=1200)
                verdict = json.loads(comp.text)
            except (llm.AIUpstreamError, json.JSONDecodeError) as exc:
                self.stdout.write(self.style.ERROR(f"  lượt {i + 1}: giám khảo lỗi {exc}"))
                continue
            w = verdict.get("winner")
            if w in wins:
                wins[w] += 1
            for m, sc in (verdict.get("scores") or {}).items():
                if m in nat and isinstance(sc, dict) and sc.get("naturalness_vi") is not None:
                    nat[m].append(float(sc["naturalness_vi"]))
        self.stdout.write(f"{'model':<34} {'thắng':>6} {'nat_vi tb':>10}")
        for m in models:
            avg = f"{statistics.mean(nat[m]):.2f}" if nat[m] else "-"
            self.stdout.write(f"{m:<34} {wins[m]:>6} {avg:>10}")
        best = max(wins, key=wins.get)
        self.stdout.write(self.style.SUCCESS(f"\n→ Nhiều lượt thắng nhất: {best} (giám khảo là LLM, chỉ tham khảo)"))
