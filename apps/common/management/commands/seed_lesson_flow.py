from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.content.models import (
    Dialogue,
    DialogueLine,
    GrammarExample,
    GrammarPoint,
    Lesson,
    LessonStep,
    Level,
    Unit,
    Vocabulary,
    VocabularyExample,
)
from apps.learning.models import LessonProgress

LESSON_CODE = "a1-u1-l4"  # "bài 4" của Unit 1 (A1)
UNIT_CODE = "a1-u1"
GRAMMAR_ORDER = 50  # tránh trùng (level, order) với grammar của seed_demo
DEMO_EMAIL = "demo@sayfully.app"


def _vocab(level, headword, pos, meaning, ipa, syllables, ipa_syllables, stress, examples):
    v, _ = Vocabulary.objects.update_or_create(
        headword=headword,
        pos=pos,
        defaults={
            "level": level,
            "meaning_vi": meaning,
            "ipa_uk": ipa,
            "ipa_us": ipa,
            "syllables": syllables,
            "ipa_syllables": ipa_syllables,
            "primary_stress": stress,
            "audio_uk_path": f"audio/uk/{headword}.mp3",
            "audio_us_path": f"audio/us/{headword}.mp3",
            "frequency_rank": 100,
        },
    )
    v.examples.all().delete()
    for i, (en, vi) in enumerate(examples):
        VocabularyExample.objects.create(vocabulary=v, order=i, text_en=en, text_vi=vi)
    return v


class Command(BaseCommand):
    help = "Ghi bài học đầy đủ 9 màn vào bài 4 (a1-u1-l4) và mở khoá nó cho user demo (idempotent)."

    @transaction.atomic
    def handle(self, *args, **opts):
        # dọn unit/lesson demo cũ nếu còn (bản seed trước đây)
        Lesson.objects.filter(code="flow-demo").delete()
        Unit.objects.filter(code="a1-flow").delete()

        a1, _ = Level.objects.update_or_create(
            code="A1",
            defaults={
                "name_vi": "Sơ cấp",
                "tier_label": "Bắt đầu nền tảng",
                "description_vi": "Cơ bản",
                "order": 1,
                "word_target": 600,
                "is_free": True,
            },
        )
        unit, _ = Unit.objects.get_or_create(
            level=a1,
            order=1,
            defaults={
                "code": UNIT_CODE,
                "title_vi": "Chào hỏi & giới thiệu",
                "title_en": "Greetings & Introductions",
                "subtitle": "Hello · Nice to meet you",
                "description_vi": "Làm quen câu chào hỏi.",
                "reward": {"coins": 150, "badge_code": "unit1_master"},
            },
        )

        morning = _vocab(
            a1, "morning", "n", "buổi sáng", "/ˈmɔː.nɪŋ/",
            ["mor", "ning"], ["ˈmɔː", "nɪŋ"], 0,
            [("Good morning, everyone!", "Chào buổi sáng mọi người!")],
        )
        friend = _vocab(
            a1, "friend", "n", "bạn bè", "/frend/",
            ["friend"], ["frend"], 0,
            [("She is my best friend.", "Cô ấy là bạn thân nhất của tôi.")],
        )
        happy = _vocab(
            a1, "happy", "adj", "vui vẻ, hạnh phúc", "/ˈhæp.i/",
            ["hap", "py"], ["ˈhæp", "i"], 0,
            [("I am happy to meet you.", "Tôi rất vui được gặp bạn.")],
        )
        student = _vocab(
            a1, "student", "n", "học sinh, sinh viên", "/ˈstjuː.dənt/",
            ["stu", "dent"], ["ˈstjuː", "dənt"], 0,
            [("I am a new student here.", "Tôi là học sinh mới ở đây.")],
        )

        gp, _ = GrammarPoint.objects.update_or_create(
            level=a1,
            order=GRAMMAR_ORDER,
            defaults={
                "category": "Thì hiện tại đơn",
                "title_vi": "Động từ to be để giới thiệu bản thân",
                "title_en": "Verb to be for introductions",
                "formula": "I + am + [danh từ / tính từ]",
                "note_vi": "Dùng \"I'm\" khi nói cho tự nhiên và thân thiện.",
                "explanation_vi": (
                    "Động từ to be (am/is/are) nối chủ ngữ với thông tin về danh tính, "
                    "cảm xúc hay trạng thái. Với chủ ngữ I luôn dùng am."
                ),
                "common_mistake_vi": "Đừng quên to be: nói \"I happy\" là sai, phải là \"I am happy\".",
                "conjugation": [
                    {"subject": "I", "form": "am"},
                    {"subject": "You / We / They", "form": "are"},
                    {"subject": "He / She / It", "form": "is"},
                ],
            },
        )
        gp.examples.all().delete()
        GrammarExample.objects.create(
            grammar_point=gp, order=0, text_en="I am a student.",
            ipa="/aɪ æm ə ˈstjuːdənt/", text_vi="Tôi là học sinh.",
        )
        GrammarExample.objects.create(
            grammar_point=gp, order=1, text_en="I am happy today.",
            ipa="/aɪ æm ˈhæpi təˈdeɪ/", text_vi="Hôm nay tôi rất vui.",
        )

        dlg, _ = Dialogue.objects.update_or_create(
            title_en="Meeting a new friend",
            defaults={"title_vi": "Làm quen bạn mới", "context_vi": "An gặp Ben trong lớp học buổi sáng."},
        )
        dlg.lines.all().delete()
        lines = [
            ("An", False, "Good morning! Are you a new student?",
             "/ɡʊd ˈmɔːnɪŋ! ɑːr juː ə njuː ˈstjuːdənt?/", "Chào buổi sáng! Bạn là học sinh mới à?"),
            ("Ben", True, "Yes, I am. My name is Ben.",
             "/jes, aɪ æm. maɪ neɪm ɪz bɛn/", "Đúng vậy. Mình tên là Ben."),
            ("An", False, "Nice to meet you, Ben. I am An.",
             "/naɪs tə miːt juː, bɛn. aɪ æm æn/", "Rất vui được gặp bạn, Ben. Mình là An."),
            ("Ben", True, "Nice to meet you too. I am happy to be here.",
             "/naɪs tə miːt juː tuː. aɪ æm ˈhæpi tə biː hɪər/", "Mình cũng vậy. Mình rất vui khi ở đây."),
        ]
        for i, (speaker, native, en, ipa, vi) in enumerate(lines):
            DialogueLine.objects.create(
                dialogue=dlg, order=i, speaker=speaker, is_native=native,
                text_en=en, ipa=ipa, text_vi=vi,
            )

        lesson, _ = Lesson.objects.update_or_create(
            code=LESSON_CODE,
            defaults={
                "unit": unit,
                "order": 4,
                "title_vi": "Chào hỏi & làm quen",
                "title_en": "Greetings & making friends",
                "description_vi": "Bài đủ 9 màn: từ vựng, ngữ pháp, hội thoại, xếp chữ, viết câu và quiz.",
                "path_subtitle_vi": "Đủ 9 màn: từ vựng → quiz",
                "est_minutes": 12,
                "xp_reward": 60,
            },
        )

        lesson.steps.all().delete()
        order = 0

        def step(**kw):
            nonlocal order
            order += 1
            LessonStep.objects.create(lesson=lesson, order=order, **kw)

        # C26 · Mở đầu bài học
        step(kind="intro", payload={
            "highlight_vi": "Học cách chào hỏi và làm quen với một người bạn mới.",
            "preview": [
                {"text_en": "Good morning!", "ipa": "/ɡʊd ˈmɔːnɪŋ/", "text_vi": "Chào buổi sáng!"},
                {"text_en": "Nice to meet you.", "ipa": "/naɪs tə miːt juː/", "text_vi": "Rất vui được gặp bạn."},
                {"text_en": "I am happy to be here.", "ipa": "/aɪ æm ˈhæpi tə biː hɪər/", "text_vi": "Tôi rất vui khi ở đây."},
            ],
        })

        # C3 · Thẻ từ mới (4 thẻ)
        step(kind="vocab", vocabulary=morning)
        step(kind="vocab", vocabulary=friend)
        step(kind="vocab", vocabulary=happy)
        step(kind="vocab", vocabulary=student)

        # C27 · Ngữ pháp trong bài
        step(kind="grammar", grammar_point=gp)

        # C28 · Hội thoại (chỉ nghe)
        step(kind="dialogue", dialogue=dlg)

        # C29 · Spelling · xếp chữ
        step(kind="spelling", vocabulary=friend, payload={
            "hint_vi": "Kéo hoặc nhấn vào các ô chữ cái theo đúng thứ tự để tạo thành từ 'bạn bè' trong tiếng Anh.",
        })

        # C29b · Luyện viết câu
        step(kind="writing", payload={
            "prompt_vi": "Viết một câu chào hỏi và giới thiệu tên của bạn.",
            "hint_vi": "Thử dùng mẫu \"Good morning, I'm ...\" nhé!",
            "suggestions": ["Good morning", "I'm ...", "Nice to meet you"],
            "xp": 20,
            "min_len": 8,
            "keywords": ["i'm", "i am", "morning", "hello", "hi"],
            "natural_tip_vi": "Người bản xứ thường dùng dạng rút gọn \"I'm An\" cho thân mật, tự nhiên.",
        })

        # C4 · Quiz cuối bài (4 câu) — C4a Mở đầu quiz do app tự suy từ số câu
        quizzes = [
            ("morning", "/ˈmɔː.nɪŋ/", ["buổi sáng", "buổi tối", "buổi trưa", "ban đêm"], 0, "morning = buổi sáng"),
            ("friend", "/frend/", ["bạn bè", "kẻ thù", "thầy giáo", "hàng xóm"], 0, "friend = bạn bè"),
            ("happy", "/ˈhæp.i/", ["vui vẻ", "buồn bã", "giận dữ", "mệt mỏi"], 0, "happy = vui vẻ"),
            ("student", "/ˈstjuː.dənt/", ["học sinh", "giáo viên", "bác sĩ", "kỹ sư"], 0, "student = học sinh"),
        ]
        for word, ipa, options, correct, expl in quizzes:
            step(kind="quiz", payload={
                "prompt_vi": "CHỌN NGHĨA ĐÚNG",
                "question_word": word,
                "question_ipa": ipa,
                "options": options,
                "correct_index": correct,
                "explanation_vi": expl,
                "xp": 10,
            })

        # Mở khoá bài 4 cho user demo: hoàn thành bài 1–3, đặt bài 4 là chặng đang học.
        unlocked_note = "(bỏ qua tiến độ: chưa có user demo — chạy seed_demo trước)"
        demo = User.objects.filter(email=DEMO_EMAIL).first()
        if demo is not None:
            prior = Lesson.objects.filter(unit=unit, order__in=[1, 2, 3])
            for les in prior:
                LessonProgress.objects.update_or_create(
                    user=demo,
                    lesson=les,
                    defaults={
                        "status": LessonProgress.Status.COMPLETED,
                        "step_index": 0,
                        "stars": 3,
                        "xp_earned": les.xp_reward,
                        "completed_at": timezone.now(),
                    },
                )
            LessonProgress.objects.update_or_create(
                user=demo,
                lesson=lesson,
                defaults={
                    "status": LessonProgress.Status.IN_PROGRESS,
                    "step_index": 0,
                    "completed_at": None,
                },
            )
            unlocked_note = "bài 1–3 = hoàn thành, bài 4 = đang học (unlocked)"

        total = lesson.steps.count()
        self.stdout.write(self.style.SUCCESS(
            f"✔ Ghi bài '{LESSON_CODE}' — {total} bước "
            f"(intro · 4 vocab · grammar · dialogue · spelling · writing · 4 quiz)."
        ))
        self.stdout.write(f"  Tiến độ demo: {unlocked_note}")
        self.stdout.write(
            f"  Mở trong app: Lộ trình A1 → Unit 1 → bài 4 '{lesson.title_vi}' (đang mở), "
            f"hoặc GET /api/v1/content/lessons/{LESSON_CODE}"
        )
