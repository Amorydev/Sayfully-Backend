"""Nạp DATA MẪU để dựng UI. Idempotent — chạy lại không nhân đôi.

Bao trọn để mọi endpoint đọc trả data thật: cấp/unit/bài (đủ bước), từ vựng (IPA/ví dụ/
collocation), ngữ pháp, hội thoại, đọc/truyện/video/shadowing/gốc từ/phrasal/IPA,
thử thách/huy hiệu/cửa hàng, gói Premium, câu xếp lớp, mã quà tặng.

    uv run python manage.py seed_demo
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.services import ensure_profile
from apps.billing.models import GiftCode, Product
from apps.common.models import LearningGoal
from apps.content.models import (
    Collocation,
    Dialogue,
    DialogueLine,
    GrammarExample,
    GrammarPoint,
    IPASound,
    Lesson,
    LessonStep,
    Level,
    LevelMilestone,
    PhrasalVerb,
    Reading,
    ReadingQuestion,
    ReadingSentence,
    ShadowingDeck,
    ShadowingSentence,
    Story,
    StoryScene,
    StorySentence,
    Topic,
    Unit,
    Video,
    Vocabulary,
    VocabularyExample,
    WordRoot,
)
from apps.gamification.models import Badge, Challenge, Game, ShopItem, UserChallenge
from apps.learning.models import DailyActivity, LessonProgress, PlacementQuestion
from apps.learning.services import local_today
from apps.notifications.models import Notification


def _vocab(headword, pos, level, meaning, ipa_uk, ipa_us, syl, ipa_syl, stress, examples, colloc):
    v, _ = Vocabulary.objects.update_or_create(
        headword=headword,
        pos=pos,
        defaults={
            "level": level,
            "meaning_vi": meaning,
            "ipa_uk": ipa_uk,
            "ipa_us": ipa_us,
            "syllables": syl,
            "ipa_syllables": ipa_syl,
            "primary_stress": stress,
            "audio_uk_path": f"audio/uk/{headword}.mp3",
            "audio_us_path": f"audio/us/{headword}.mp3",
            "frequency_rank": 100,
        },
    )
    v.examples.all().delete()
    for i, (en, vi) in enumerate(examples):
        VocabularyExample.objects.create(vocabulary=v, order=i, text_en=en, text_vi=vi)
    v.collocations.all().delete()
    for en, vi in colloc:
        Collocation.objects.create(vocabulary=v, text_en=en, meaning_vi=vi)
    return v


class Command(BaseCommand):
    help = "Nạp data mẫu để dựng UI (idempotent)."

    @transaction.atomic
    def handle(self, *args, **opts):
        a1, _ = Level.objects.update_or_create(
            code="A1",
            defaults={"name_vi": "Sơ cấp", "tier_label": "Bắt đầu nền tảng",
                      "description_vi": "Cơ bản", "order": 1,
                      "word_target": 600, "is_free": True},
        )
        a2, _ = Level.objects.update_or_create(
            code="A2",
            defaults={"name_vi": "Sơ trung cấp", "tier_label": "Xây nền vững chắc",
                      "description_vi": "Câu ngắn", "order": 2,
                      "word_target": 800, "is_free": False},
        )
        higher_levels = [
            ("B1", "Trung cấp", "Giao tiếp tự tin", "Giao tiếp tự tin về các chủ đề quen thuộc", 3, 1200),
            ("B2", "Trung cao cấp", "Trôi chảy nâng cao", "Thảo luận trôi chảy, trình bày ý kiến rõ ràng", 4, 2000),
            ("C1", "Cao cấp", "Thành thạo học thuật", "Dùng ngôn ngữ linh hoạt trong công việc, học thuật", 5, 3200),
            ("C2", "Thành thạo", "Gần như bản xứ", "Sử dụng gần như người bản xứ", 6, 5000),
        ]
        for code, name_vi, tier_label, desc_vi, order, word_target in higher_levels:
            Level.objects.update_or_create(
                code=code,
                defaults={"name_vi": name_vi, "tier_label": tier_label, "description_vi": desc_vi,
                          "order": order, "word_target": word_target, "is_free": False},
            )

        travel, _ = Topic.objects.update_or_create(
            code="travel", defaults={"name_vi": "Du lịch", "name_en": "Travel", "icon": "flight"}
        )
        Topic.objects.update_or_create(
            code="business", defaults={"name_vi": "Công sở", "name_en": "Business", "icon": "work"}
        )

        apple = _vocab("apple", "n", a1, "quả táo", "/ˈæp.əl/", "/ˈæp.əl/", ["ap", "ple"],
                       ["ˈæp", "əl"], 0, [("I eat an apple every day.", "Tôi ăn một quả táo mỗi ngày.")],
                       [("red apple", "táo đỏ")])
        beautiful = _vocab("beautiful", "adj", a1, "đẹp, xinh đẹp", "/ˈbjuː.tɪ.fəl/", "/ˈbjuː.t̬ə.fəl/",
                           ["beau", "ti", "ful"], ["ˈbjuː", "tɪ", "fəl"], 0,
                           [("She has a beautiful voice.", "Cô ấy có một giọng hát rất đẹp."),
                            ("It was a beautiful sunny morning.", "Đó là một buổi sáng đầy nắng tuyệt đẹp.")],
                           [("beautiful day", "ngày đẹp trời")])
        understand = _vocab("understand", "v", a1, "hiểu, thấu hiểu", "/ˌʌn.dəˈstænd/", "/ˌʌn.dɚˈstænd/",
                            ["un", "der", "stand"], ["ˌʌn", "dər", "ˈstænd"], 2,
                            [("I understand the lesson.", "Tôi hiểu bài học.")], [])
        family = _vocab("family", "n", a1, "gia đình", "/ˈfæm.əl.i/", "/ˈfæm.əl.i/", ["fam", "i", "ly"],
                        ["ˈfæm", "əl", "i"], 0,
                        [("I have a small family.", "Tôi có một gia đình nhỏ.")], [])
        apple.topics.add(travel)
        beautiful.topics.add(travel)

        gp, _ = GrammarPoint.objects.update_or_create(
            level=a1, order=1,
            defaults={"category": "Thì", "title_vi": "Động từ to be với 'I'",
                      "title_en": "To be with I", "formula": "I + am + [tên / tính từ]",
                      "explanation_vi": "Từ am chỉ đi với chủ ngữ I.",
                      "common_mistake_vi": "Không dùng 'I is'.",
                      "conjugation": [{"subject": "I", "form": "am"},
                                      {"subject": "He / She / It", "form": "is"},
                                      {"subject": "You / We / They", "form": "are"}]},
        )
        gp.examples.all().delete()
        GrammarExample.objects.create(grammar_point=gp, order=0, text_en="I am a student.",
                                      ipa="/aɪ æm ə ˈstjuːdnt/", text_vi="Tôi là học sinh.")

        dlg, _ = Dialogue.objects.update_or_create(
            title_en="At the coffee shop",
            defaults={"title_vi": "Tại quán cà phê", "context_vi": "Linh gặp Tom lần đầu."},
        )
        dlg.lines.all().delete()
        DialogueLine.objects.create(dialogue=dlg, order=0, speaker="Linh", is_native=False,
                                    text_en="Hi, excuse me, is this seat taken?",
                                    ipa="/haɪ, ɪkˈskjuːz miː, ɪz ðɪs ˈsiːt ˈteɪkən?/",
                                    text_vi="Xin chào, chỗ này có ai ngồi chưa ạ?")
        DialogueLine.objects.create(dialogue=dlg, order=1, speaker="Tom", is_native=True,
                                    text_en="No, it's free. Please, sit down!",
                                    ipa="/noʊ, ɪts ˈfriː. ˈpliːz, ˈsɪt daʊn!/",
                                    text_vi="Không, chỗ trống đấy. Bạn cứ ngồi đi!")

        unit, _ = Unit.objects.update_or_create(
            level=a1, order=1,
            defaults={"code": "a1-u1", "title_vi": "Chào hỏi & giới thiệu",
                      "title_en": "Greetings & Introductions", "subtitle": "Hello · Nice to meet you",
                      "description_vi": "Làm quen câu chào hỏi.",
                      "reward": {"coins": 150, "badge_code": "unit1_master"}},
        )
        lesson, _ = Lesson.objects.update_or_create(
            unit=unit, order=1,
            defaults={"code": "a1-u1-l1", "title_vi": "Bài 3: Hỏi thăm", "title_en": "Asking",
                      "description_vi": "Học cách hỏi thăm.", "est_minutes": 12, "xp_reward": 50},
        )
        lesson.steps.all().delete()
        LessonStep.objects.create(lesson=lesson, order=1, kind="intro",
                                  payload={"highlight_vi": "Học cách hỏi thăm và trả lời.",
                                           "preview": [{"text_en": "How are you?", "ipa": "/haʊ ɑːr juː/",
                                                        "text_vi": "Bạn có khoẻ không?"}]})
        LessonStep.objects.create(lesson=lesson, order=2, kind="vocab", vocabulary=beautiful)
        LessonStep.objects.create(lesson=lesson, order=3, kind="grammar", grammar_point=gp)
        LessonStep.objects.create(lesson=lesson, order=4, kind="dialogue", dialogue=dlg)
        LessonStep.objects.create(lesson=lesson, order=5, kind="quiz",
                                  payload={"prompt_vi": "CHỌN NGHĨA ĐÚNG", "question_word": "understand",
                                           "question_ipa": "/ˌʌn.dɚˈstænd/",
                                           "options": ["hiểu", "quên", "nói", "nghe"],
                                           "correct_index": 0, "explanation_vi": "understand = hiểu",
                                           "xp": 10})
        country = _vocab("country", "n", a1, "quốc gia, đất nước", "/ˈkʌn.tri/", "/ˈkʌn.tri/",
                         ["coun", "try"], ["ˈkʌn", "tri"], 0,
                         [("Vietnam is a beautiful country.", "Việt Nam là một đất nước xinh đẹp.")],
                         [("home country", "quê hương")])
        nationality = _vocab("nationality", "n", a1, "quốc tịch",
                             "/ˌnæʃ.ənˈæl.ə.ti/", "/ˌnæʃ.əˈnæl.ə.t̬i/",
                             ["na", "tion", "al", "i", "ty"], ["ˌnæʃ", "ən", "ˈæl", "ə", "ti"], 2,
                             [("What is your nationality?", "Quốc tịch của bạn là gì?")],
                             [("dual nationality", "hai quốc tịch")])
        lesson2, _ = Lesson.objects.update_or_create(
            unit=unit, order=2,
            defaults={"code": "a1-u1-l2", "title_vi": "Bài 4: Quốc tịch", "title_en": "Nationality",
                      "description_vi": "Nói về quốc tịch và đất nước.",
                      "est_minutes": 10, "xp_reward": 50},
        )
        lesson2.steps.all().delete()
        LessonStep.objects.create(
            lesson=lesson2, order=1, kind="intro",
            payload={"highlight_vi": "Giới thiệu quốc tịch và đất nước của bạn.",
                     "preview": [{"text_en": "Where are you from?", "ipa": "/weər ɑːr juː frɒm/",
                                  "text_vi": "Bạn đến từ đâu?"},
                                 {"text_en": "I'm from Vietnam.", "ipa": "/aɪm frɒm ˌvjetˈnɑːm/",
                                  "text_vi": "Tôi đến từ Việt Nam."}]},
        )
        LessonStep.objects.create(lesson=lesson2, order=2, kind="vocab", vocabulary=country)
        LessonStep.objects.create(lesson=lesson2, order=3, kind="spelling", vocabulary=nationality,
                                  payload={"hint_vi": "Ghép các chữ cái thành từ 'quốc tịch'."})
        LessonStep.objects.create(lesson=lesson2, order=4, kind="grammar", grammar_point=gp)
        LessonStep.objects.create(lesson=lesson2, order=5, kind="dialogue", dialogue=dlg)
        LessonStep.objects.create(
            lesson=lesson2, order=6, kind="quiz",
            payload={"prompt_vi": "CHỌN NGHĨA ĐÚNG", "question_word": "nationality",
                     "question_ipa": "/ˌnæʃ.əˈnæl.ə.ti/",
                     "options": ["quốc tịch", "quốc gia", "thành phố", "ngôn ngữ"],
                     "correct_index": 0, "explanation_vi": "nationality = quốc tịch", "xp": 10},
        )

        unit2, _ = Unit.objects.update_or_create(
            level=a1, order=2,
            defaults={"code": "a1-u2", "title_vi": "Gia đình & bạn bè",
                      "title_en": "Family & Friends", "subtitle": "People around you",
                      "description_vi": "Nói về gia đình và miêu tả mọi người.",
                      "reward": {"coins": 150, "badge_code": "unit2_master"}},
        )
        u2l1, _ = Lesson.objects.update_or_create(
            unit=unit2, order=1,
            defaults={"code": "a1-u2-l1", "title_vi": "Bài 1: Thành viên gia đình",
                      "title_en": "Family members", "description_vi": "Từ vựng về gia đình.",
                      "est_minutes": 11, "xp_reward": 50},
        )
        u2l1.steps.all().delete()
        LessonStep.objects.create(
            lesson=u2l1, order=1, kind="intro",
            payload={"highlight_vi": "Học từ vựng về các thành viên trong gia đình.",
                     "preview": [{"text_en": "This is my family.", "ipa": "/ðɪs ɪz maɪ ˈfæməli/",
                                  "text_vi": "Đây là gia đình tôi."}]},
        )
        LessonStep.objects.create(lesson=u2l1, order=2, kind="vocab", vocabulary=family)
        LessonStep.objects.create(lesson=u2l1, order=3, kind="grammar", grammar_point=gp)
        LessonStep.objects.create(
            lesson=u2l1, order=4, kind="quiz",
            payload={"prompt_vi": "CHỌN NGHĨA ĐÚNG", "question_word": "family",
                     "question_ipa": "/ˈfæm.əl.i/",
                     "options": ["gia đình", "bạn bè", "đất nước", "trường học"],
                     "correct_index": 0, "explanation_vi": "family = gia đình", "xp": 10},
        )
        u2l2, _ = Lesson.objects.update_or_create(
            unit=unit2, order=2,
            defaults={"code": "a1-u2-l2", "title_vi": "Bài 2: Miêu tả người",
                      "title_en": "Describing people", "description_vi": "Dùng tính từ miêu tả.",
                      "est_minutes": 12, "xp_reward": 60},
        )
        u2l2.steps.all().delete()
        LessonStep.objects.create(
            lesson=u2l2, order=1, kind="intro",
            payload={"highlight_vi": "Dùng tính từ để miêu tả ngoại hình và tính cách.",
                     "preview": [{"text_en": "She is very kind.", "ipa": "/ʃiː ɪz ˈveri kaɪnd/",
                                  "text_vi": "Cô ấy rất tốt bụng."}]},
        )
        LessonStep.objects.create(lesson=u2l2, order=2, kind="vocab", vocabulary=beautiful)
        LessonStep.objects.create(lesson=u2l2, order=3, kind="spelling", vocabulary=beautiful,
                                  payload={"hint_vi": "Ghép các chữ cái thành từ 'đẹp'."})
        LessonStep.objects.create(lesson=u2l2, order=4, kind="dialogue", dialogue=dlg)
        LessonStep.objects.create(
            lesson=u2l2, order=5, kind="quiz",
            payload={"prompt_vi": "CHỌN NGHĨA ĐÚNG", "question_word": "beautiful",
                     "question_ipa": "/ˈbjuː.tɪ.fəl/",
                     "options": ["đẹp", "xấu", "cao", "nhanh"],
                     "correct_index": 0, "explanation_vi": "beautiful = đẹp", "xp": 10},
        )

        extra_units = [
            (3, "a1-u3", "Số đếm, thời gian & ngày tháng", "Numbers, Time & Dates",
             "Everyday information", "Đếm số, xem giờ và nói ngày tháng.",
             [("a1-u3-l1", "Bài 1: Số đếm", "Numbers", understand),
              ("a1-u3-l2", "Bài 2: Xem giờ", "Telling time", country)]),
            (4, "a1-u4", "Đồ ăn & thức uống", "Food & Drinks",
             "Ordering at a café", "Gọi món và trả tiền tại quán.",
             [("a1-u4-l1", "Bài 1: Gọi món", "Ordering food", apple),
              ("a1-u4-l2", "Bài 2: Thức uống", "Drinks", beautiful)]),
            (5, "a1-u5", "Thói quen hằng ngày", "Daily Routines",
             "Talk about your day", "Miêu tả một ngày của bạn.",
             [("a1-u5-l1", "Bài 1: Buổi sáng", "Morning routine", family),
              ("a1-u5-l2", "Bài 2: Buổi tối", "Evening routine", nationality)]),
        ]
        for order, ucode, uvi, uen, usub, udesc, lessons_spec in extra_units:
            u, _ = Unit.objects.update_or_create(
                level=a1, order=order,
                defaults={"code": ucode, "title_vi": uvi, "title_en": uen,
                          "subtitle": usub, "description_vi": udesc,
                          "reward": {"coins": 150, "badge_code": f"{ucode}_master"}},
            )
            for i, (lcode, lvi, l_en, lvocab) in enumerate(lessons_spec, start=1):
                les, _ = Lesson.objects.update_or_create(
                    unit=u, order=i,
                    defaults={"code": lcode, "title_vi": lvi, "title_en": l_en,
                              "description_vi": lvi, "est_minutes": 10, "xp_reward": 50},
                )
                les.steps.all().delete()
                LessonStep.objects.create(
                    lesson=les, order=1, kind="intro",
                    payload={"highlight_vi": f"{lvi} — luyện tập cùng EnGo.",
                             "preview": [{"text_en": lvocab.headword.capitalize(),
                                          "ipa": lvocab.ipa_us, "text_vi": lvocab.meaning_vi}]},
                )
                LessonStep.objects.create(lesson=les, order=2, kind="vocab", vocabulary=lvocab)
                LessonStep.objects.create(
                    lesson=les, order=3, kind="quiz",
                    payload={"prompt_vi": "CHỌN NGHĨA ĐÚNG", "question_word": lvocab.headword,
                             "question_ipa": lvocab.ipa_us,
                             "options": [lvocab.meaning_vi, "nghĩa khác", "không đúng", "chưa rõ"],
                             "correct_index": 0,
                             "explanation_vi": f"{lvocab.headword} = {lvocab.meaning_vi}", "xp": 10},
                )

        LevelMilestone.objects.update_or_create(
            level=a1, order=1,
            defaults={"code": "a1-1", "name": "A1.1", "title_vi": "Chứng chỉ Milestone A1.1",
                      "requirement_lessons": 5, "reward_xp": 150, "reward_coins": 0},
        )

        # Đọc / truyện / video / shadowing / tra cứu — mỗi loại 1 mẫu
        rd, _ = Reading.objects.update_or_create(
            level=a1, order=1,
            defaults={"title_en": "My family", "title_vi": "Gia đình tôi", "topic": travel,
                      "est_minutes": 2},
        )
        rd.sentences.all().delete()
        ReadingSentence.objects.create(reading=rd, order=0, text_en="I have a small and loving family.",
                                       ipa="/aɪ hæv ə smɔːl ænd ˈlʌvɪŋ ˈfæməli/",
                                       text_vi="Tôi có một gia đình nhỏ và yêu thương.")
        rd.questions.all().delete()
        ReadingQuestion.objects.create(reading=rd, order=0, question_en="How is the family?",
                                       options=["Big", "Small", "Old", "New"], answer_index=1)

        st, _ = Story.objects.update_or_create(
            level=a1, order=1,
            defaults={"title_en": "The Teacher's Apple", "title_vi": "Quả táo của cô giáo",
                      "genre": "daily", "synopsis_vi": "Tom tặng cô giáo quả táo."},
        )
        st.scenes.all().delete()
        sc = StoryScene.objects.create(story=st, order=0)
        StorySentence.objects.create(scene=sc, order=0,
                                     text_en="Every morning, Tom brings a shiny red apple.",
                                     text_vi="Mỗi sáng, Tom mang một quả táo đỏ bóng.")

        Video.objects.update_or_create(
            youtube_id="demo_vid_1",
            defaults={"level": a1, "title_vi": "Gọi cà phê như người bản xứ",
                      "title_en": "Ordering Coffee", "category": "Hội thoại", "duration_sec": 165},
        )

        sd, _ = ShadowingDeck.objects.update_or_create(
            level=a1, order=1,
            defaults={"title_en": "The Teacher's Apple", "title_vi": "Quả táo cô giáo",
                      "focus_vi": "Âm /æ/ & ngữ điệu", "est_seconds": 105},
        )
        sd.sentences.all().delete()
        ShadowingSentence.objects.create(deck=sd, order=0,
                                         text_en="She took a fresh red apple from the counter.",
                                         ipa="/ʃiː tʊk ə frɛʃ rɛd ˈæpəl frəm ðə ˈkaʊntər/",
                                         text_vi="Cô lấy một quả táo đỏ tươi từ quầy.")

        root, _ = WordRoot.objects.update_or_create(
            kind="prefix", text="un-",
            defaults={"meaning_vi": "không / ngược lại", "group_vi": "Phủ định",
                      "mnemonic_vi": "un- đảo ngược nghĩa."},
        )
        root.examples.add(understand)
        PhrasalVerb.objects.update_or_create(
            text="get up",
            defaults={"verb_group": "get", "ipa": "/ɡet ʌp/", "meaning_vi": "thức dậy",
                      "explanation_vi": "Rời giường sau khi ngủ.", "level": a1,
                      "examples": [{"en": "I get up at 6.", "vi": "Tôi dậy lúc 6 giờ.", "audio_path": ""}]},
        )
        IPASound.objects.update_or_create(
            symbol="iː",
            defaults={"kind": "vowel", "description_vi": "Nguyên âm dài",
                      "articulation_vi": "Môi dẹt, hai khoé miệng bè rộng như mỉm cười.",
                      "sample_words": ["sheep", "see", "tea"],
                      "minimal_pair": {"other": "ɪ", "words": ["sheep", "ship"]}},
        )

        # Game hoá
        for code, scope, metric, title, target, rx, rc in [
            ("daily_xp", "daily", "xp", "Kiếm 30 XP", 30, 0, 15),
            ("daily_words", "daily", "words", "Ôn 20 từ", 20, 0, 15),
            ("daily_speak", "daily", "speaking", "Nói 5 câu", 5, 20, 0),
            ("weekly_lessons", "weekly", "lessons", "Học 10 bài trong tuần", 10, 100, 50),
        ]:
            Challenge.objects.update_or_create(
                code=code, defaults={"scope": scope, "metric": metric, "title_vi": title,
                                     "description_vi": title, "target": target,
                                     "reward_xp": rx, "reward_coins": rc},
            )
        for code, title, metric, value in [
            ("streak7", "Chuỗi 7 ngày", "streak", 7),
            ("streak30", "Chuỗi 30 ngày", "streak", 30),
            ("level5", "Đạt cấp 5", "level", 5),
        ]:
            Badge.objects.update_or_create(
                code=code, defaults={"title_vi": title, "description_vi": title,
                                     "condition": {"metric": metric, "value": value}},
            )
        for code, title, desc, cost, effect in [
            ("refill_hearts", "Bơm đầy tim", "Hồi phục 5/5 tim", 150, {"hearts": 5}),
            ("streak_freeze", "Băng bảo vệ streak", "Đóng băng chuỗi 24h", 200, {"streak_freeze": 1}),
            ("xp_boost", "Gấp đôi XP", "x2 XP trong 15 phút", 120, {"xp_boost": 15}),
        ]:
            ShopItem.objects.update_or_create(
                code=code, defaults={"title_vi": title, "description_vi": desc,
                                     "cost_coins": cost, "effect": effect},
            )
        for code, title, kind in [("word_rain", "Mưa từ vựng", "reflex"),
                                  ("match_pairs", "Ghép cặp", "memory"),
                                  ("stress_master", "Bậc thầy trọng âm", "reflex")]:
            Game.objects.update_or_create(
                code=code, defaults={"title_vi": title, "description_vi": title, "kind": kind},
            )

        # Thanh toán
        for code, name, period, price, orig, trial, badge, order in [
            ("premium_month", "Gói Tháng", "month", 59000, None, 0, "", 1),
            ("premium_year", "Gói Năm", "year", 499000, 999000, 7, "TIẾT KIỆM 50%", 2),
            ("premium_lifetime", "Trọn đời", "lifetime", 699000, None, 0, "", 3),
        ]:
            Product.objects.update_or_create(
                code=code, defaults={"name_vi": name, "period": period, "price": price,
                                     "original_price": orig, "trial_days": trial, "badge_vi": badge,
                                     "features": ["Mở khoá A2–C2", "Gia sư AI", "Không quảng cáo"],
                                     "order": order},
            )
        GiftCode.objects.update_or_create(code="SAYFULLY30", defaults={"days": 30, "max_uses": 100})

        # Xếp lớp
        for i, (skill, level, prompt, opts, ans) in enumerate([
            ("vocab", "A1", "Choose: an ___ a day.", ["apple", "car", "book", "dog"], 0),
            ("grammar", "A1", "She ___ to school.", ["go", "goes", "going", "went"], 1),
            ("listening", "A2", "Choose the correct word.", ["ship", "sheep", "shop", "shape"], 1),
        ]):
            PlacementQuestion.objects.update_or_create(
                order=i + 1, defaults={"skill": skill, "level": level, "prompt_en": prompt,
                                       "options": opts, "answer_index": ans},
            )

        # Tài khoản demo có sẵn tiến độ để preview Home (demo@sayfully.app / demo1234)
        demo, created = User.objects.get_or_create(
            email="demo@sayfully.app", defaults={"full_name": "Quyền Vũ"}
        )
        if created:
            demo.set_password("demo1234")
            demo.save(update_fields=["password"])
        p = ensure_profile(demo)
        p.cefr_level = "A1"
        p.goal_level = "B1"
        p.learning_goal = LearningGoal.DAILY
        p.level = 4
        p.xp_total = 1240
        p.coins = 520
        p.hearts = 5
        p.streak_current = 3
        p.streak_best = 7
        p.daily_goal_words = 10
        p.daily_goal_xp = 50
        p.save()

        today = local_today(p)
        DailyActivity.objects.update_or_create(
            user=demo, date=today,
            defaults={"words_reviewed": 4, "minutes": 12, "xp": 30,
                      "lessons_completed": 0, "speaking_count": 2},
        )
        LessonProgress.objects.update_or_create(
            user=demo, lesson=lesson,
            defaults={"status": LessonProgress.Status.IN_PROGRESS, "step_index": 2},
        )
        for code, progress in (("daily_xp", 30), ("daily_words", 14), ("daily_speak", 2)):
            UserChallenge.objects.update_or_create(
                user=demo, challenge=Challenge.objects.get(code=code),
                period_key=today.isoformat(), defaults={"progress": progress},
            )
        if not Notification.objects.filter(user=demo).exists():
            for title in ("Chào mừng đến EnGo!", "Bạn có 14 từ đến hạn ôn",
                          "Chuỗi 3 ngày — giữ vững nhé!"):
                Notification.objects.create(
                    user=demo, kind=Notification.Kind.SYSTEM, title_vi=title
                )

        self.stdout.write(self.style.SUCCESS(
            f"Xong. Levels={Level.objects.count()} Vocab={Vocabulary.objects.count()} "
            f"Lessons={Lesson.objects.count()} Challenges={Challenge.objects.count()} "
            f"Shop={ShopItem.objects.count()} Products={Product.objects.count()} "
            f"Demo=demo@sayfully.app/demo1234"
        ))
