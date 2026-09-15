"""Nạp DATA MẪU để dựng UI. Idempotent — chạy lại không nhân đôi.

Bao trọn để mọi endpoint đọc trả data thật: cấp/unit/bài (đủ bước), từ vựng (IPA/ví dụ/
collocation), ngữ pháp, hội thoại, đọc/truyện/video/shadowing/gốc từ/phrasal/IPA,
thử thách/huy hiệu/cửa hàng, gói Premium, câu xếp lớp, mã quà tặng.

    uv run python manage.py seed_demo
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone as djtz

from apps.accounts.models import User
from apps.accounts.services import ensure_profile
from apps.ai.models import RoleplayScenario
from apps.billing.models import GiftCode, Product
from apps.common.models import LearningGoal
from apps.content.management.commands.seed_ipa import seed_ipa_sounds
from apps.content.management.commands.seed_roots import seed_word_roots
from apps.content.models import (
    Collocation,
    Dialogue,
    DialogueLine,
    GrammarExample,
    GrammarPoint,
    Lesson,
    LessonStep,
    Level,
    LevelMilestone,
    ListeningItem,
    ListeningTopic,
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
    VideoSubtitle,
    Vocabulary,
    VocabularyDeck,
    VocabularyDeckCollection,
    VocabularyDeckItem,
    VocabularyExample,
)
from apps.content.video_transcript import load_subtitle_source, replace_video_subtitles
from apps.gamification.models import (
    Badge,
    Challenge,
    Game,
    LeagueGroup,
    LeagueMembership,
    ShopItem,
    UserChallenge,
)
from apps.learning.models import (
    DailyActivity,
    LessonProgress,
    ListeningTopicProgress,
    PlacementQuestion,
    SpeakingTopicProgress,
    SRSCard,
    WeeklyStat,
)
from apps.learning.services import local_today
from apps.notifications.models import Notification


def _vocab(
    headword,
    pos,
    level,
    meaning,
    ipa_uk,
    ipa_us,
    syl,
    ipa_syl,
    stress,
    examples,
    colloc,
    definition_vi="",
    synonyms=None,
    antonyms=None,
):
    v, _ = Vocabulary.objects.update_or_create(
        headword=headword,
        pos=pos,
        defaults={
            "level": level,
            "meaning_vi": meaning,
            "definition_vi": definition_vi,
            "ipa_uk": ipa_uk,
            "ipa_us": ipa_us,
            "syllables": syl,
            "ipa_syllables": ipa_syl,
            "primary_stress": stress,
            "audio_uk_path": f"audio/uk/{headword}.mp3",
            "audio_us_path": f"audio/us/{headword}.mp3",
            "frequency_rank": 100,
            "synonyms": synonyms or [],
            "antonyms": antonyms or [],
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
            defaults={
                "name_vi": "Sơ cấp",
                "tier_label": "Bắt đầu nền tảng",
                "description_vi": "Cơ bản",
                "order": 1,
                "word_target": 600,
                "is_free": True,
            },
        )
        a2, _ = Level.objects.update_or_create(
            code="A2",
            defaults={
                "name_vi": "Sơ trung cấp",
                "tier_label": "Xây nền vững chắc",
                "description_vi": "Câu ngắn",
                "order": 2,
                "word_target": 800,
                "is_free": True,
            },
        )
        higher_levels = [
            (
                "B1",
                "Trung cấp",
                "Giao tiếp tự tin",
                "Giao tiếp tự tin về các chủ đề quen thuộc",
                3,
                1200,
            ),
            (
                "B2",
                "Trung cao cấp",
                "Trôi chảy nâng cao",
                "Thảo luận trôi chảy, trình bày ý kiến rõ ràng",
                4,
                2000,
            ),
            (
                "C1",
                "Cao cấp",
                "Thành thạo học thuật",
                "Dùng ngôn ngữ linh hoạt trong công việc, học thuật",
                5,
                3200,
            ),
            ("C2", "Thành thạo", "Gần như bản xứ", "Sử dụng gần như người bản xứ", 6, 5000),
        ]
        for code, name_vi, tier_label, desc_vi, order, word_target in higher_levels:
            Level.objects.update_or_create(
                code=code,
                defaults={
                    "name_vi": name_vi,
                    "tier_label": tier_label,
                    "description_vi": desc_vi,
                    "order": order,
                    "word_target": word_target,
                    "is_free": True,
                },
            )

        travel, _ = Topic.objects.update_or_create(
            code="travel", defaults={"name_vi": "Du lịch", "name_en": "Travel", "icon": "flight"}
        )
        Topic.objects.update_or_create(
            code="business", defaults={"name_vi": "Công sở", "name_en": "Business", "icon": "work"}
        )

        apple = _vocab(
            "apple",
            "n",
            a1,
            "quả táo",
            "/ˈæp.əl/",
            "/ˈæp.əl/",
            ["ap", "ple"],
            ["ˈæp", "əl"],
            0,
            [("I eat an apple every day.", "Tôi ăn một quả táo mỗi ngày.")],
            [("red apple", "táo đỏ")],
        )
        beautiful = _vocab(
            "beautiful",
            "adj",
            a1,
            "đẹp, xinh đẹp",
            "/ˈbjuː.tɪ.fəl/",
            "/ˈbjuː.t̬ə.fəl/",
            ["beau", "ti", "ful"],
            ["ˈbjuː", "tɪ", "fəl"],
            0,
            [
                ("She has a beautiful voice.", "Cô ấy có một giọng hát rất đẹp."),
                ("It was a beautiful sunny morning.", "Đó là một buổi sáng đầy nắng tuyệt đẹp."),
            ],
            [("beautiful day", "ngày đẹp trời")],
            definition_vi="Có vẻ đẹp hoặc làm người khác cảm thấy dễ chịu.",
            synonyms=["lovely", "gorgeous"],
            antonyms=["ugly"],
        )
        understand = _vocab(
            "understand",
            "v",
            a1,
            "hiểu, thấu hiểu",
            "/ˌʌn.dəˈstænd/",
            "/ˌʌn.dɚˈstænd/",
            ["un", "der", "stand"],
            ["ˌʌn", "dər", "ˈstænd"],
            2,
            [("I understand the lesson.", "Tôi hiểu bài học.")],
            [],
        )
        family = _vocab(
            "family",
            "n",
            a1,
            "gia đình",
            "/ˈfæm.əl.i/",
            "/ˈfæm.əl.i/",
            ["fam", "i", "ly"],
            ["ˈfæm", "əl", "i"],
            0,
            [("I have a small family.", "Tôi có một gia đình nhỏ.")],
            [],
        )
        apple.topics.add(travel)
        beautiful.topics.add(travel)

        gp, _ = GrammarPoint.objects.update_or_create(
            level=a1,
            order=1,
            defaults={
                "category": "Thì",
                "title_vi": "Động từ to be với 'I'",
                "title_en": "To be with I",
                "formula": "I + am + [tên / tính từ]",
                "note_vi": 'Trong giao tiếp hằng ngày, "I am" luôn đi liền để xưng hô bản thân!',
                "explanation_vi": "Đại từ I (tôi) luôn đi với động từ to be am ở thì hiện "
                "tại đơn để giới thiệu danh tính, cảm xúc hoặc trạng thái.",
                "common_mistake_vi": "Trong văn nói tự nhiên, người bản xứ hầu như luôn dùng "
                "dạng rút gọn I'm thay vì I am.",
                "conjugation": [
                    {"subject": "Khẳng định", "form": "I am… / I'm…"},
                    {"subject": "Phủ định", "form": "I am not… / I'm not…"},
                ],
            },
        )
        gp.examples.all().delete()
        GrammarExample.objects.create(
            grammar_point=gp,
            order=0,
            text_en="I am a student.",
            ipa="/aɪ æm ə ˈstjuːdnt/",
            text_vi="Tôi là học sinh.",
        )
        GrammarExample.objects.create(
            grammar_point=gp,
            order=1,
            text_en="I'm from Vietnam.",
            ipa="/aɪm frɒm ˌvjetˈnɑːm/",
            text_vi="Tôi đến từ Việt Nam.",
        )

        dlg, _ = Dialogue.objects.update_or_create(
            title_en="At the coffee shop",
            defaults={"title_vi": "Tại quán cà phê", "context_vi": "Linh gặp Tom lần đầu."},
        )
        dlg.lines.all().delete()
        DialogueLine.objects.create(
            dialogue=dlg,
            order=0,
            speaker="Linh",
            is_native=False,
            text_en="Hi, excuse me, is this seat taken?",
            ipa="/haɪ, ɪkˈskjuːz miː, ɪz ðɪs ˈsiːt ˈteɪkən?/",
            text_vi="Xin chào, chỗ này có ai ngồi chưa ạ?",
        )
        DialogueLine.objects.create(
            dialogue=dlg,
            order=1,
            speaker="Tom",
            is_native=True,
            text_en="No, it's free. Please, sit down!",
            ipa="/noʊ, ɪts ˈfriː. ˈpliːz, ˈsɪt daʊn!/",
            text_vi="Không, chỗ trống đấy. Bạn cứ ngồi đi!",
        )

        unit, _ = Unit.objects.update_or_create(
            level=a1,
            order=1,
            defaults={
                "code": "a1-u1",
                "title_vi": "Chào hỏi & giới thiệu",
                "title_en": "Greetings & Introductions",
                "subtitle": "Hello · Nice to meet you",
                "description_vi": "Làm quen câu chào hỏi.",
                "reward": {"coins": 150, "badge_code": "unit1_master"},
            },
        )
        lesson, _ = Lesson.objects.update_or_create(
            unit=unit,
            order=1,
            defaults={
                "code": "a1-u1-l1",
                "title_vi": "Hello & goodbye",
                "title_en": "Hello & goodbye",
                "description_vi": "Khởi động phát âm tự nhiên.",
                "path_subtitle_vi": "Khởi động phát âm tự nhiên",
                "est_minutes": 8,
                "xp_reward": 20,
            },
        )
        lesson.steps.all().delete()
        LessonStep.objects.create(
            lesson=lesson,
            order=1,
            kind="intro",
            payload={
                "highlight_vi": "Học cách hỏi thăm và trả lời.",
                "preview": [
                    {
                        "text_en": "How are you?",
                        "ipa": "/haʊ ɑːr juː/",
                        "text_vi": "Bạn có khoẻ không?",
                    }
                ],
            },
        )
        LessonStep.objects.create(lesson=lesson, order=2, kind="vocab", vocabulary=beautiful)
        LessonStep.objects.create(lesson=lesson, order=3, kind="grammar", grammar_point=gp)
        LessonStep.objects.create(lesson=lesson, order=4, kind="dialogue", dialogue=dlg)
        LessonStep.objects.create(
            lesson=lesson,
            order=5,
            kind="spelling",
            payload={
                "word": "hello",
                "meaning_vi": "xin chào",
                "ipa": "/həˈləʊ/",
                "hint_vi": "Kéo hoặc nhấn vào các ô chữ cái theo đúng "
                "thứ tự để tạo thành từ hoàn chỉnh trong tiếng Anh.",
            },
        )
        LessonStep.objects.create(
            lesson=lesson,
            order=6,
            kind="writing",
            payload={
                "prompt_vi": "Viết câu giới thiệu tên bạn",
                "hint_vi": "Thử dùng mẫu câu đơn giản trước nhé!",
                "suggestions": ["My name is...", "I'm...", "Nice to meet you"],
                "xp": 20,
                "min_len": 8,
                "keywords": ["name", "i'm", "i am"],
                "natural_tip_vi": "Người bản xứ thường dùng dạng rút gọn "
                '"I\'m Minh" để câu văn thêm thân mật và '
                "gần gũi trong giao tiếp hàng ngày.",
            },
        )
        LessonStep.objects.create(
            lesson=lesson,
            order=7,
            kind="quiz",
            payload={
                "prompt_vi": "CHỌN NGHĨA ĐÚNG",
                "question_word": "understand",
                "question_ipa": "/ˌʌn.dɚˈstænd/",
                "options": ["hiểu", "quên", "nói", "nghe"],
                "correct_index": 0,
                "explanation_vi": "understand = hiểu",
                "xp": 10,
            },
        )
        country = _vocab(
            "country",
            "n",
            a1,
            "quốc gia, đất nước",
            "/ˈkʌn.tri/",
            "/ˈkʌn.tri/",
            ["coun", "try"],
            ["ˈkʌn", "tri"],
            0,
            [("Vietnam is a beautiful country.", "Việt Nam là một đất nước xinh đẹp.")],
            [("home country", "quê hương")],
        )
        nationality = _vocab(
            "nationality",
            "n",
            a1,
            "quốc tịch",
            "/ˌnæʃ.ənˈæl.ə.ti/",
            "/ˌnæʃ.əˈnæl.ə.t̬i/",
            ["na", "tion", "al", "i", "ty"],
            ["ˌnæʃ", "ən", "ˈæl", "ə", "ti"],
            2,
            [("What is your nationality?", "Quốc tịch của bạn là gì?")],
            [("dual nationality", "hai quốc tịch")],
        )
        lesson2, _ = Lesson.objects.update_or_create(
            unit=unit,
            order=2,
            defaults={
                "code": "a1-u1-l2",
                "title_vi": "Giới thiệu bản thân",
                "title_en": "Introducing yourself",
                "description_vi": "Đại từ và câu chào hỏi cơ bản.",
                "path_subtitle_vi": "Đại từ & câu chào hỏi cơ bản",
                "est_minutes": 10,
                "xp_reward": 20,
            },
        )
        lesson2.steps.all().delete()
        LessonStep.objects.create(
            lesson=lesson2,
            order=1,
            kind="intro",
            payload={
                "highlight_vi": "Giới thiệu quốc tịch và đất nước của bạn.",
                "preview": [
                    {
                        "text_en": "Where are you from?",
                        "ipa": "/weər ɑːr juː frɒm/",
                        "text_vi": "Bạn đến từ đâu?",
                    },
                    {
                        "text_en": "I'm from Vietnam.",
                        "ipa": "/aɪm frɒm ˌvjetˈnɑːm/",
                        "text_vi": "Tôi đến từ Việt Nam.",
                    },
                ],
            },
        )
        LessonStep.objects.create(lesson=lesson2, order=2, kind="vocab", vocabulary=country)
        LessonStep.objects.create(
            lesson=lesson2,
            order=3,
            kind="spelling",
            vocabulary=nationality,
            payload={"hint_vi": "Ghép các chữ cái thành từ 'quốc tịch'."},
        )
        LessonStep.objects.create(lesson=lesson2, order=4, kind="grammar", grammar_point=gp)
        LessonStep.objects.create(lesson=lesson2, order=5, kind="dialogue", dialogue=dlg)
        LessonStep.objects.create(
            lesson=lesson2,
            order=6,
            kind="quiz",
            payload={
                "prompt_vi": "CHỌN NGHĨA ĐÚNG",
                "question_word": "nationality",
                "question_ipa": "/ˌnæʃ.əˈnæl.ə.ti/",
                "options": ["quốc tịch", "quốc gia", "thành phố", "ngôn ngữ"],
                "correct_index": 0,
                "explanation_vi": "nationality = quốc tịch",
                "xp": 10,
            },
        )

        lesson3, _ = Lesson.objects.update_or_create(
            unit=unit,
            order=3,
            defaults={
                "code": "a1-u1-l3",
                "title_vi": "Hỏi thăm",
                "title_en": "Asking how someone is",
                "description_vi": "Hỏi thăm và phản hồi tự nhiên.",
                "path_subtitle_vi": "Hỏi thăm và phản hồi tự nhiên",
                "est_minutes": 12,
                "xp_reward": 20,
            },
        )
        lesson3.steps.all().delete()
        LessonStep.objects.create(
            lesson=lesson3,
            order=1,
            kind="intro",
            payload={
                "highlight_vi": "Hỏi thăm và trả lời một cách tự nhiên.",
                "preview": [
                    {
                        "text_en": "How are you?",
                        "ipa": "/haʊ ɑːr juː/",
                        "text_vi": "Bạn có khỏe không?",
                    }
                ],
            },
        )
        LessonStep.objects.create(lesson=lesson3, order=2, kind="vocab", vocabulary=understand)
        LessonStep.objects.create(
            lesson=lesson3,
            order=3,
            kind="quiz",
            payload={
                "prompt_vi": "CHỌN NGHĨA ĐÚNG",
                "question_word": "How are you?",
                "question_ipa": "/haʊ ɑːr juː/",
                "options": [
                    "Bạn có khỏe không?",
                    "Bạn tên là gì?",
                    "Bạn ở đâu?",
                    "Bạn làm nghề gì?",
                ],
                "correct_index": 0,
                "explanation_vi": "How are you? dùng để hỏi thăm.",
                "xp": 10,
            },
        )

        lesson4, _ = Lesson.objects.update_or_create(
            unit=unit,
            order=4,
            defaults={
                "code": "a1-u1-l4",
                "title_vi": "Quốc gia & quốc tịch",
                "title_en": "Countries & nationalities",
                "description_vi": "Giới thiệu quê hương và quốc tịch.",
                "path_subtitle_vi": "Giới thiệu quê hương và quốc tịch",
                "est_minutes": 10,
                "xp_reward": 20,
            },
        )
        lesson4.steps.all().delete()
        LessonStep.objects.create(
            lesson=lesson4,
            order=1,
            kind="intro",
            payload={
                "highlight_vi": "Giới thiệu đất nước và quốc tịch của bạn.",
                "preview": [
                    {
                        "text_en": "I'm from Vietnam.",
                        "ipa": "/aɪm frəm ˌvjetˈnɑːm/",
                        "text_vi": "Tôi đến từ Việt Nam.",
                    }
                ],
            },
        )
        LessonStep.objects.create(lesson=lesson4, order=2, kind="vocab", vocabulary=country)
        LessonStep.objects.create(
            lesson=lesson4,
            order=3,
            kind="spelling",
            vocabulary=nationality,
            payload={"hint_vi": "Ghép các chữ cái thành từ 'quốc tịch'."},
        )

        lesson5, _ = Lesson.objects.update_or_create(
            unit=unit,
            order=5,
            defaults={
                "code": "a1-u1-l5",
                "title_vi": "Nghề nghiệp",
                "title_en": "Occupations",
                "description_vi": "Nói về công việc của bạn.",
                "path_subtitle_vi": "Nói về công việc của bạn",
                "est_minutes": 10,
                "xp_reward": 20,
            },
        )
        lesson5.steps.all().delete()
        LessonStep.objects.create(
            lesson=lesson5,
            order=1,
            kind="intro",
            payload={
                "highlight_vi": "Tập hỏi và trả lời về nghề nghiệp.",
                "preview": [
                    {
                        "text_en": "What do you do?",
                        "ipa": "/wɒt duː juː duː/",
                        "text_vi": "Bạn làm nghề gì?",
                    }
                ],
            },
        )
        LessonStep.objects.create(lesson=lesson5, order=2, kind="vocab", vocabulary=family)

        lesson6, _ = Lesson.objects.update_or_create(
            unit=unit,
            order=6,
            defaults={
                "code": "a1-u1-l6",
                "title_vi": "Ôn tập Unit 1",
                "title_en": "Unit 1 review",
                "description_vi": "Ôn tập và mở khóa rương phần thưởng.",
                "path_subtitle_vi": "Ôn tập và mở khóa rương phần thưởng",
                "est_minutes": 12,
                "xp_reward": 20,
            },
        )
        lesson6.steps.all().delete()
        LessonStep.objects.create(
            lesson=lesson6,
            order=1,
            kind="quiz",
            payload={
                "prompt_vi": "ÔN TẬP UNIT 1",
                "question_word": "Hello",
                "question_ipa": "/həˈləʊ/",
                "options": ["Xin chào", "Tạm biệt", "Cảm ơn", "Xin lỗi"],
                "correct_index": 0,
                "explanation_vi": "Hello = Xin chào.",
                "xp": 10,
            },
        )

        unit2, _ = Unit.objects.update_or_create(
            level=a1,
            order=2,
            defaults={
                "code": "a1-u2",
                "title_vi": "Gia đình & bạn bè",
                "title_en": "Family & Friends",
                "subtitle": "People around you",
                "description_vi": "Nói về gia đình và miêu tả mọi người.",
                "reward": {"coins": 150, "badge_code": "unit2_master"},
            },
        )
        u2l1, _ = Lesson.objects.update_or_create(
            unit=unit2,
            order=1,
            defaults={
                "code": "a1-u2-l1",
                "title_vi": "Bài 1: Thành viên gia đình",
                "title_en": "Family members",
                "description_vi": "Từ vựng về gia đình.",
                "path_subtitle_vi": "Từ vựng về các thành viên trong gia đình",
                "est_minutes": 11,
                "xp_reward": 50,
            },
        )
        u2l1.steps.all().delete()
        LessonStep.objects.create(
            lesson=u2l1,
            order=1,
            kind="intro",
            payload={
                "highlight_vi": "Học từ vựng về các thành viên trong gia đình.",
                "preview": [
                    {
                        "text_en": "This is my family.",
                        "ipa": "/ðɪs ɪz maɪ ˈfæməli/",
                        "text_vi": "Đây là gia đình tôi.",
                    }
                ],
            },
        )
        LessonStep.objects.create(lesson=u2l1, order=2, kind="vocab", vocabulary=family)
        LessonStep.objects.create(lesson=u2l1, order=3, kind="grammar", grammar_point=gp)
        LessonStep.objects.create(
            lesson=u2l1,
            order=4,
            kind="quiz",
            payload={
                "prompt_vi": "CHỌN NGHĨA ĐÚNG",
                "question_word": "family",
                "question_ipa": "/ˈfæm.əl.i/",
                "options": ["gia đình", "bạn bè", "đất nước", "trường học"],
                "correct_index": 0,
                "explanation_vi": "family = gia đình",
                "xp": 10,
            },
        )
        u2l2, _ = Lesson.objects.update_or_create(
            unit=unit2,
            order=2,
            defaults={
                "code": "a1-u2-l2",
                "title_vi": "Bài 2: Miêu tả người",
                "title_en": "Describing people",
                "description_vi": "Dùng tính từ miêu tả.",
                "path_subtitle_vi": "Dùng tính từ để miêu tả người",
                "est_minutes": 12,
                "xp_reward": 60,
            },
        )
        u2l2.steps.all().delete()
        LessonStep.objects.create(
            lesson=u2l2,
            order=1,
            kind="intro",
            payload={
                "highlight_vi": "Dùng tính từ để miêu tả ngoại hình và tính cách.",
                "preview": [
                    {
                        "text_en": "She is very kind.",
                        "ipa": "/ʃiː ɪz ˈveri kaɪnd/",
                        "text_vi": "Cô ấy rất tốt bụng.",
                    }
                ],
            },
        )
        LessonStep.objects.create(lesson=u2l2, order=2, kind="vocab", vocabulary=beautiful)
        LessonStep.objects.create(
            lesson=u2l2,
            order=3,
            kind="spelling",
            vocabulary=beautiful,
            payload={"hint_vi": "Ghép các chữ cái thành từ 'đẹp'."},
        )
        LessonStep.objects.create(lesson=u2l2, order=4, kind="dialogue", dialogue=dlg)
        LessonStep.objects.create(
            lesson=u2l2,
            order=5,
            kind="quiz",
            payload={
                "prompt_vi": "CHỌN NGHĨA ĐÚNG",
                "question_word": "beautiful",
                "question_ipa": "/ˈbjuː.tɪ.fəl/",
                "options": ["đẹp", "xấu", "cao", "nhanh"],
                "correct_index": 0,
                "explanation_vi": "beautiful = đẹp",
                "xp": 10,
            },
        )

        extra_units = [
            (
                3,
                "a1-u3",
                "Số đếm, thời gian & ngày tháng",
                "Numbers, Time & Dates",
                "Everyday information",
                "Đếm số, xem giờ và nói ngày tháng.",
                [
                    ("a1-u3-l1", "Bài 1: Số đếm", "Numbers", understand),
                    ("a1-u3-l2", "Bài 2: Xem giờ", "Telling time", country),
                ],
            ),
            (
                4,
                "a1-u4",
                "Đồ ăn & thức uống",
                "Food & Drinks",
                "Ordering at a café",
                "Gọi món và trả tiền tại quán.",
                [
                    ("a1-u4-l1", "Bài 1: Gọi món", "Ordering food", apple),
                    ("a1-u4-l2", "Bài 2: Thức uống", "Drinks", beautiful),
                ],
            ),
            (
                5,
                "a1-u5",
                "Thói quen hằng ngày",
                "Daily Routines",
                "Talk about your day",
                "Miêu tả một ngày của bạn.",
                [
                    ("a1-u5-l1", "Bài 1: Buổi sáng", "Morning routine", family),
                    ("a1-u5-l2", "Bài 2: Buổi tối", "Evening routine", nationality),
                ],
            ),
        ]
        for order, ucode, uvi, uen, usub, udesc, lessons_spec in extra_units:
            u, _ = Unit.objects.update_or_create(
                level=a1,
                order=order,
                defaults={
                    "code": ucode,
                    "title_vi": uvi,
                    "title_en": uen,
                    "subtitle": usub,
                    "description_vi": udesc,
                    "reward": {"coins": 150, "badge_code": f"{ucode}_master"},
                },
            )
            for i, (lcode, lvi, l_en, lvocab) in enumerate(lessons_spec, start=1):
                les, _ = Lesson.objects.update_or_create(
                    unit=u,
                    order=i,
                    defaults={
                        "code": lcode,
                        "title_vi": lvi,
                        "title_en": l_en,
                        "description_vi": lvi,
                        "path_subtitle_vi": f"Luyện tập {lvi.lower()}",
                        "est_minutes": 10,
                        "xp_reward": 50,
                    },
                )
                les.steps.all().delete()
                LessonStep.objects.create(
                    lesson=les,
                    order=1,
                    kind="intro",
                    payload={
                        "highlight_vi": f"{lvi} — luyện tập cùng EnGo.",
                        "preview": [
                            {
                                "text_en": lvocab.headword.capitalize(),
                                "ipa": lvocab.ipa_us,
                                "text_vi": lvocab.meaning_vi,
                            }
                        ],
                    },
                )
                LessonStep.objects.create(lesson=les, order=2, kind="vocab", vocabulary=lvocab)
                LessonStep.objects.create(
                    lesson=les,
                    order=3,
                    kind="quiz",
                    payload={
                        "prompt_vi": "CHỌN NGHĨA ĐÚNG",
                        "question_word": lvocab.headword,
                        "question_ipa": lvocab.ipa_us,
                        "options": [lvocab.meaning_vi, "nghĩa khác", "không đúng", "chưa rõ"],
                        "correct_index": 0,
                        "explanation_vi": f"{lvocab.headword} = {lvocab.meaning_vi}",
                        "xp": 10,
                    },
                )

        LevelMilestone.objects.update_or_create(
            level=a1,
            order=1,
            defaults={
                "code": "a1-1",
                "name": "A1.1",
                "title_vi": "Chứng chỉ Milestone A1.1",
                "requirement_lessons": 5,
                "reward_xp": 150,
                "reward_coins": 0,
            },
        )

        # Đọc / truyện / video / shadowing / tra cứu — mỗi loại 1 mẫu
        rd, _ = Reading.objects.update_or_create(
            level=a1,
            order=1,
            defaults={
                "title_en": "My family",
                "title_vi": "Gia đình tôi",
                "topic": travel,
                "est_minutes": 2,
            },
        )
        rd.sentences.all().delete()
        ReadingSentence.objects.create(
            reading=rd,
            order=0,
            text_en="I have a small and loving family.",
            ipa="/aɪ hæv ə smɔːl ænd ˈlʌvɪŋ ˈfæməli/",
            text_vi="Tôi có một gia đình nhỏ và yêu thương.",
        )
        rd.questions.all().delete()
        ReadingQuestion.objects.create(
            reading=rd,
            order=0,
            question_en="How is the family?",
            options=["Big", "Small", "Old", "New"],
            answer_index=1,
        )

        st, _ = Story.objects.update_or_create(
            level=a1,
            order=1,
            defaults={
                "title_en": "The Teacher's Apple",
                "title_vi": "Quả táo của cô giáo",
                "genre": "daily",
                "synopsis_vi": "Tom tặng cô giáo quả táo.",
            },
        )
        st.scenes.all().delete()
        sc = StoryScene.objects.create(story=st, order=0)
        StorySentence.objects.create(
            scene=sc,
            order=0,
            text_en="Every morning, Tom brings a shiny red apple.",
            text_vi="Mỗi sáng, Tom mang một quả táo đỏ bóng.",
        )

        b1 = Level.objects.get(code="B1")
        _videos = [
            (
                "t6-fT0hjTvc",
                b1,
                "Dịch vụ giao hàng của Kiki — Trailer tiếng Anh",
                "Kiki's Delivery Service — Official English Trailer",
                "Phim",
                50,
            ),
            (
                "EGFdtq8lk0c",
                a2,
                "Check-in sân bay suôn sẻ",
                "At the Airport Departure",
                "Hội thoại",
                192,
            ),
            (
                "SSAWEDhszA8",
                b1,
                "Nói về công việc của bạn",
                "Talking About Your Job",
                "Công sở",
                325,
            ),
            (
                "q_UYw-tHBCY",
                a2,
                "Khám phá ngôi nhà trên cây",
                "Secret Treehouse Mystery",
                "Phim",
                220,
            ),
            (
                "7cTumvjrm3g",
                b1,
                "Toy Story — Hành trình trưởng thành",
                "Toy Story Tribute",
                "Phim",
                113,
            ),
        ]
        for yid, lv, tvi, ten, cat, dur in _videos:
            Video.objects.update_or_create(
                youtube_id=yid,
                defaults={
                    "level": lv,
                    "title_vi": tvi,
                    "title_en": ten,
                    "category": cat,
                    "duration_sec": dur,
                    "is_free": True,
                },
            )
        Video.objects.filter(youtube_id="demo_vid_1").delete()

        _subs = {
            # Video thật từ Parroto/YouTube. Không giữ transcript demo cũ vì nội dung
            # "cozy weekend" không thuộc video này; phụ đề chuẩn sẽ được import riêng.
            "SSAWEDhszA8": [],
            # Trailer Kiki cần transcript biên tập có timestamp thật. Nạp bằng
            # import_video_subtitles; không seed câu giả/chia đều thời lượng.
            "t6-fT0hjTvc": [],
            "EGFdtq8lk0c": [
                (
                    "Good morning, may I see your passport and ticket?",
                    "/ɡʊd ˈmɔːr.nɪŋ meɪ aɪ siː jɔːr ˈpæs.pɔːrt ænd ˈtɪk.ɪt/",
                    "Chào buổi sáng, cho tôi xem hộ chiếu và vé của bạn nhé?",
                ),
                (
                    "Here you are. I'd like a window seat, please.",
                    "/hɪr juː ɑːr aɪd laɪk ə ˈwɪn.doʊ siːt pliːz/",
                    "Của bạn đây. Cho tôi chỗ ngồi cạnh cửa sổ nhé.",
                ),
                (
                    "Do you have any bags to check in?",
                    "/duː juː hæv ˈɛn.i bæɡz tuː tʃɛk ɪn/",
                    "Bạn có hành lý nào cần ký gửi không?",
                ),
                (
                    "Just one suitcase and this small backpack.",
                    "/dʒʌst wʌn ˈsuːt.keɪs ænd ðɪs smɔːl ˈbæk.pæk/",
                    "Chỉ một vali và chiếc ba lô nhỏ này thôi.",
                ),
                (
                    "Your flight boards at gate twenty-two at ten.",
                    "/jɔːr flaɪt bɔːrdz æt ɡeɪt ˈtwɛn.ti tuː æt tɛn/",
                    "Chuyến bay của bạn lên máy bay ở cổng 22 lúc mười giờ.",
                ),
            ],
            "q_UYw-tHBCY": [
                (
                    "Nobody knows who built this treehouse in the woods.",
                    "/ˈnoʊ.bɒd.i noʊz huː bɪlt ðɪs ˈtriː.haʊs ɪn ðə wʊdz/",
                    "Không ai biết ai đã dựng ngôi nhà trên cây trong rừng này.",
                ),
                (
                    "A faint light flickered behind the tiny window.",
                    "/ə feɪnt laɪt ˈflɪk.ərd bɪˈhaɪnd ðə ˈtaɪ.ni ˈwɪn.doʊ/",
                    "Một ánh sáng mờ nhạt lập lòe sau ô cửa sổ nhỏ.",
                ),
                (
                    "We climbed the old ladder, one careful step at a time.",
                    "/wiː klaɪmd ðə oʊld ˈlæd.ər wʌn ˈkɛr.fəl stɛp æt ə taɪm/",
                    "Chúng tôi trèo lên chiếc thang cũ, từng bước thật cẩn thận.",
                ),
                (
                    "Inside, a dusty map pointed to a hidden door.",
                    "/ɪnˈsaɪd ə ˈdʌs.ti mæp ˈpɔɪn.tɪd tuː ə ˈhɪd.ən dɔːr/",
                    "Bên trong, một tấm bản đồ phủ bụi chỉ tới một cánh cửa bí mật.",
                ),
                (
                    "Whatever waited there had been asleep for years.",
                    "/wɒtˈɛv.ər ˈweɪ.tɪd ðɛr hæd biːn əˈsliːp fɔːr jɪrz/",
                    "Bất cứ thứ gì chờ đợi ở đó đã ngủ yên suốt nhiều năm.",
                ),
            ],
        }
        for yid, lines in _subs.items():
            vid = Video.objects.get(youtube_id=yid)
            vid.subtitles.all().delete()
            span = max(vid.duration_sec * 1000 // max(len(lines), 1), 3000)
            for i, (en, ipa, vi) in enumerate(lines):
                VideoSubtitle.objects.create(
                    video=vid,
                    order=i + 1,
                    start_ms=i * span,
                    end_ms=(i + 1) * span,
                    text_en=en,
                    ipa=ipa,
                    text_vi=vi,
                )

        # Lesson video thật, giữ source JSON để seed/dev/deploy đều tái tạo cùng dữ liệu.
        toy_story_video = Video.objects.get(youtube_id="7cTumvjrm3g")
        toy_story_source = settings.BASE_DIR / "apps/content/data/video_7cTumvjrm3g.json"
        replace_video_subtitles(toy_story_video, load_subtitle_source(toy_story_source))

        sd, _ = ShadowingDeck.objects.update_or_create(
            level=a1,
            order=1,
            defaults={
                "title_en": "Greetings & Introductions",
                "title_vi": "Chào hỏi & giới thiệu",
                "focus_vi": "Ngữ điệu câu chào",
                "est_seconds": 180,
                "icon": "greeting",
                "color": "#4F46E5",
            },
        )
        sd.sentences.all().delete()
        for j, (en, ipa, vi, goal, highlights) in enumerate(
            [
                (
                    "Hello, nice to meet you.",
                    "/həˈloʊ naɪs tə miːt juː/",
                    "Xin chào, rất vui được gặp bạn.",
                    'Nhấn rõ trọng âm từ "meet"',
                    [{"text": "meet", "kind": "primary_stress"}],
                ),
                (
                    "My name is Long. What's yours?",
                    "/maɪ neɪm ɪz lɒŋ wɒts jɔːz/",
                    "Tôi tên Long. Còn bạn?",
                    'Giữ nhịp tự nhiên ở cụm "What\'s yours"',
                    [{"text": "yours", "kind": "intonation"}],
                ),
                (
                    "Where are you from?",
                    "/wɛər ɑːr juː frɒm/",
                    "Bạn đến từ đâu?",
                    "Lên giọng nhẹ ở cuối câu hỏi",
                    [{"text": "from", "kind": "rising_intonation"}],
                ),
                (
                    "I'm from Vietnam.",
                    "/aɪm frəm ˌvjɛtˈnɑːm/",
                    "Tôi đến từ Việt Nam.",
                    'Nhấn trọng âm chính của "Vietnam"',
                    [{"text": "Vietnam", "kind": "primary_stress"}],
                ),
            ]
        ):
            ShadowingSentence.objects.create(
                deck=sd,
                order=j,
                text_en=en,
                ipa=ipa,
                text_vi=vi,
                speaking_goal_vi=goal,
                highlights=highlights,
            )

        seed_word_roots()  # 40 gốc từ (C40)
        PhrasalVerb.objects.update_or_create(
            text="get up",
            defaults={
                "verb_group": "get",
                "ipa": "/ɡet ʌp/",
                "meaning_vi": "thức dậy",
                "explanation_vi": "Rời giường sau khi ngủ.",
                "level": a1,
                "examples": [
                    {"en": "I get up at 6.", "vi": "Tôi dậy lúc 6 giờ.", "audio_path": ""}
                ],
            },
        )
        seed_ipa_sounds()  # 44 âm IPA (C43)

        # Game hoá
        for code, scope, metric, title, target, rx, rc in [
            ("daily_xp", "daily", "xp", "Kiếm 100 XP hôm nay", 100, 0, 20),
            ("daily_words", "daily", "words", "Ôn 20 từ vựng", 20, 0, 15),
            ("daily_speak", "daily", "speaking", "Phát âm chuẩn 15 câu", 15, 0, 25),
            ("weekly_lessons", "weekly", "lessons", "Học 10 bài trong tuần", 10, 100, 50),
        ]:
            Challenge.objects.update_or_create(
                code=code,
                defaults={
                    "scope": scope,
                    "metric": metric,
                    "title_vi": title,
                    "description_vi": title,
                    "target": target,
                    "reward_xp": rx,
                    "reward_coins": rc,
                },
            )
        for code, title, metric, value in [
            ("streak7", "Chuỗi 7 ngày", "streak", 7),
            ("streak30", "Chuỗi 30 ngày", "streak", 30),
            ("level5", "Đạt cấp 5", "level", 5),
        ]:
            Badge.objects.update_or_create(
                code=code,
                defaults={
                    "title_vi": title,
                    "description_vi": title,
                    "condition": {"metric": metric, "value": value},
                },
            )
        # (code, title, desc, cost, effect, category, order, discount_pct, meta)
        for code, title, desc, cost, effect, cat, order, pct, meta in [
            (
                "refill_hearts",
                "Bơm đầy tim",
                "Hồi phục 5/5 tim",
                150,
                {"hearts": 5},
                "booster",
                1,
                0,
                {},
            ),
            (
                "streak_freeze",
                "Băng bảo vệ streak",
                "Đóng băng chuỗi 24h",
                200,
                {"streak_freeze": 1},
                "booster",
                2,
                0,
                {},
            ),
            (
                "xp_boost",
                "Gấp đôi XP",
                "x2 XP trong 15 phút",
                120,
                {"xp_boost": 15},
                "booster",
                3,
                0,
                {},
            ),
            (
                "xp_boost_60",
                "Gấp đôi XP · 1 giờ",
                "x2 XP trong 60 phút",
                350,
                {"xp_boost": 60},
                "booster",
                4,
                20,
                {},
            ),
            (
                "bundle_week",
                "Gói bảo vệ tuần",
                "2 băng streak + bơm đầy tim",
                500,
                {"streak_freeze": 2, "hearts": 5},
                "bundle",
                10,
                20,
                {},
            ),
            (
                "bundle_grind",
                "Gói cày XP",
                "x2 XP 30 phút + bơm đầy tim",
                400,
                {"xp_boost": 30, "hearts": 5},
                "bundle",
                11,
                15,
                {},
            ),
            (
                "mystery_box",
                "Rương may mắn",
                "Ngẫu nhiên: xu, tim, băng hoặc boost XP",
                120,
                {"mystery_box": 1},
                "special",
                20,
                0,
                {},
            ),
            (
                "streak_repair",
                "Hồi sinh streak",
                "Khôi phục chuỗi vừa mất trong 48h",
                350,
                {"streak_repair": 1},
                "special",
                21,
                0,
                {},
            ),
            (
                "premium_day",
                "1 ngày Premium",
                "Mở khoá toàn bộ nội dung 24h",
                1000,
                {"premium_days": 1},
                "special",
                22,
                0,
                {},
            ),
            (
                "frame_gold",
                "Khung Hoàng Kim",
                "Viền avatar vàng óng",
                500,
                {"cosmetic": 1},
                "cosmetic",
                30,
                0,
                {"slot": "avatar_frame", "colors": ["#FFE082", "#FFB300", "#FF8F00"]},
            ),
            (
                "frame_aurora",
                "Khung Cực Quang",
                "Viền avatar xanh tím chuyển sắc",
                800,
                {"cosmetic": 1},
                "cosmetic",
                31,
                0,
                {"slot": "avatar_frame", "colors": ["#5EEAD4", "#818CF8", "#F472B6"]},
            ),
            (
                "frame_neon",
                "Khung Neon",
                "Viền avatar hồng neon",
                650,
                {"cosmetic": 1},
                "cosmetic",
                32,
                0,
                {"slot": "avatar_frame", "colors": ["#FF4DDB", "#8B5CF6"]},
            ),
        ]:
            ShopItem.objects.update_or_create(
                code=code,
                defaults={
                    "title_vi": title,
                    "description_vi": desc,
                    "cost_coins": cost,
                    "effect": effect,
                    "category": cat,
                    "order": order,
                    "discount_pct": pct,
                    "meta": meta,
                },
            )
        for code, title, desc, kind, featured, order in [
            ("word_rain", "Mưa từ vựng", "Hứng bóng chữ rơi đúng nghĩa", "reflex", True, 1),
            ("match_pairs", "Ghép cặp", "Nối từ tiếng Anh và nghĩa Việt", "memory", False, 2),
            (
                "stress_master",
                "Bậc thầy trọng âm",
                "Bắt đúng âm tiết được nhấn",
                "reflex",
                False,
                3,
            ),
            ("speed_type", "Gõ nhanh 60s", "Thử thách tốc độ gõ phím", "reflex", False, 4),
        ]:
            Game.objects.update_or_create(
                code=code,
                defaults={
                    "title_vi": title,
                    "description_vi": desc,
                    "kind": kind,
                    "is_featured": featured,
                    "order": order,
                },
            )

        # Thanh toán
        for code, name, period, price, orig, trial, badge, order in [
            ("premium_month", "Gói Tháng", "month", 59000, None, 0, "", 1),
            ("premium_year", "Gói Năm", "year", 499000, 999000, 7, "TIẾT KIỆM 50%", 2),
            ("premium_lifetime", "Trọn đời", "lifetime", 699000, None, 0, "", 3),
        ]:
            Product.objects.update_or_create(
                code=code,
                defaults={
                    "name_vi": name,
                    "kind": "premium",
                    "period": period,
                    "price": price,
                    "original_price": orig,
                    "trial_days": trial,
                    "badge_vi": badge,
                    "features": [
                        "Mở khoá A2–C2",
                        "Gia sư AI",
                        "Không quảng cáo",
                        "+50% xu mọi nguồn",
                    ],
                    "order": order,
                },
            )
        for code, name, coins, price, badge, order in [
            ("coins_500", "500 xu", 500, 19000, "", 10),
            ("coins_1200", "1.200 xu", 1200, 39000, "PHỔ BIẾN", 11),
            ("coins_3000", "3.000 xu", 3000, 79000, "LỢI NHẤT", 12),
        ]:
            Product.objects.update_or_create(
                code=code,
                defaults={
                    "name_vi": name,
                    "kind": "coins",
                    "coins": coins,
                    "period": "one_time",
                    "price": price,
                    "badge_vi": badge,
                    "features": [],
                    "order": order,
                },
            )
        GiftCode.objects.update_or_create(code="SAYFULLY30", defaults={"days": 30, "max_uses": 100})

        # Xếp lớp
        for i, (skill, level, prompt, opts, ans) in enumerate(
            [
                ("vocab", "A1", "Choose: an ___ a day.", ["apple", "car", "book", "dog"], 0),
                ("grammar", "A1", "She ___ to school.", ["go", "goes", "going", "went"], 1),
                (
                    "listening",
                    "A2",
                    "Choose the correct word.",
                    ["ship", "sheep", "shop", "shape"],
                    1,
                ),
            ]
        ):
            PlacementQuestion.objects.update_or_create(
                order=i + 1,
                defaults={
                    "skill": skill,
                    "level": level,
                    "prompt_en": prompt,
                    "options": opts,
                    "answer_index": ans,
                },
            )

        # Thêm nội dung để counts Trung tâm luyện tập (C19) khớp design
        # + làm chủ đề luyện nói (C8a): icon, est_seconds, cờ Premium, vài câu mỗi deck
        _speaking_sets = [
            (
                "Shopping",
                "Mua sắm",
                "shopping",
                210,
                True,
                [
                    ("How much is this?", "/haʊ mʌtʃ ɪz ðɪs/", "Cái này bao nhiêu tiền?"),
                    (
                        "Do you have a smaller size?",
                        "/duː juː hæv ə ˈsmɔːlər saɪz/",
                        "Bạn có cỡ nhỏ hơn không?",
                    ),
                    ("I'll take it, thanks.", "/aɪl teɪk ɪt θæŋks/", "Tôi lấy cái này, cảm ơn."),
                ],
            ),
            (
                "Travel",
                "Du lịch",
                "travel",
                240,
                True,
                [
                    ("Where is the station?", "/wɛər ɪz ðə ˈsteɪʃən/", "Nhà ga ở đâu?"),
                    (
                        "One ticket to the city, please.",
                        "/wʌn ˈtɪkɪt tə ðə ˈsɪti pliːz/",
                        "Cho tôi một vé vào thành phố.",
                    ),
                ],
            ),
            (
                "At the Restaurant",
                "Ở nhà hàng",
                "restaurant",
                200,
                True,
                [
                    (
                        "A table for two, please.",
                        "/ə ˈteɪbəl fɔːr tuː pliːz/",
                        "Cho bàn hai người.",
                    ),
                    (
                        "Can I see the menu?",
                        "/kæn aɪ siː ðə ˈmɛnjuː/",
                        "Cho tôi xem thực đơn được không?",
                    ),
                ],
            ),
            (
                "At Work",
                "Ở nơi làm việc",
                "work",
                260,
                True,
                [
                    (
                        "Let's schedule a meeting.",
                        "/lɛts ˈskɛdʒuːl ə ˈmiːtɪŋ/",
                        "Hãy lên lịch một cuộc họp.",
                    ),
                    (
                        "Could you send me the file?",
                        "/kʊd juː sɛnd miː ðə faɪl/",
                        "Bạn gửi tôi tệp được không?",
                    ),
                ],
            ),
            (
                "Job Interview",
                "Phỏng vấn xin việc",
                "interview",
                300,
                False,
                [
                    (
                        "Tell me about yourself.",
                        "/tɛl miː əˈbaʊt jɔːˈsɛlf/",
                        "Hãy giới thiệu về bản thân bạn.",
                    )
                ],
            ),
        ]
        _speaking_colors = {
            "shopping": "#22C55E",
            "travel": "#38BDF8",
            "restaurant": "#FF6B57",
            "work": "#7C3AED",
            "interview": "#F59E0B",
            "greeting": "#4F46E5",
        }
        for i, (ten, tvi, icon, secs, _is_free, sents) in enumerate(_speaking_sets, start=2):
            deck, _ = ShadowingDeck.objects.update_or_create(
                level=a1,
                order=i,
                defaults={
                    "title_en": ten,
                    "title_vi": tvi,
                    "icon": icon,
                    "color": _speaking_colors.get(icon, ""),
                    "est_seconds": secs,
                    "is_free": True,
                },
            )
            deck.sentences.all().delete()
            for j, (en, ipa, vi) in enumerate(sents):
                ShadowingSentence.objects.create(
                    deck=deck, order=j, text_en=en, ipa=ipa, text_vi=vi
                )

        # Luyện nghe (C9a/C9): chủ đề + câu; mode "choose" dùng blank_index/options/answer_index
        _listen_sets = [
            (
                "Chào hỏi & giới thiệu",
                "greeting",
                240,
                True,
                [
                    (
                        "Hello, nice to meet you.",
                        "Xin chào, rất vui được gặp bạn.",
                        3,
                        ["meet", "meat", "mit", "meal"],
                        0,
                    ),
                    ("What is your name?", "Bạn tên là gì?", 3, ["name", "game", "same", "aim"], 0),
                    (
                        "I am from Vietnam.",
                        "Tôi đến từ Việt Nam.",
                        2,
                        ["from", "form", "farm", "free"],
                        0,
                    ),
                    (
                        "How are you today?",
                        "Hôm nay bạn thế nào?",
                        1,
                        ["are", "our", "hour", "air"],
                        0,
                    ),
                ],
            ),
            (
                "Mua sắm & Giá cả",
                "shopping",
                220,
                True,
                [
                    (
                        "How much is this shirt?",
                        "Cái áo này bao nhiêu tiền?",
                        1,
                        ["much", "match", "mush", "march"],
                        0,
                    ),
                    (
                        "Do you have a smaller size?",
                        "Bạn có cỡ nhỏ hơn không?",
                        4,
                        ["smaller", "similar", "summer", "smell"],
                        0,
                    ),
                    (
                        "I would like to pay by card.",
                        "Tôi muốn trả bằng thẻ.",
                        4,
                        ["pay", "play", "pray", "pie"],
                        0,
                    ),
                ],
            ),
            (
                "Du lịch & Khách sạn",
                "travel",
                260,
                True,
                [
                    (
                        "Where is the train station?",
                        "Nhà ga tàu ở đâu?",
                        3,
                        ["train", "rain", "trane", "brain"],
                        0,
                    ),
                    (
                        "I booked a room for two nights.",
                        "Tôi đã đặt phòng cho hai đêm.",
                        5,
                        ["two", "too", "to", "tow"],
                        0,
                    ),
                    (
                        "Can I check in early?",
                        "Tôi nhận phòng sớm được không?",
                        4,
                        ["early", "eary", "ear", "oily"],
                        0,
                    ),
                ],
            ),
            (
                "Ở nhà hàng & Gọi món",
                "restaurant",
                200,
                True,
                [
                    (
                        "A table for two, please.",
                        "Cho bàn hai người.",
                        2,
                        ["for", "four", "far", "fore"],
                        0,
                    ),
                    (
                        "Can I see the menu?",
                        "Cho tôi xem thực đơn?",
                        4,
                        ["menu", "many", "money", "meno"],
                        0,
                    ),
                    (
                        "The soup is very hot.",
                        "Món súp rất nóng.",
                        4,
                        ["hot", "hat", "heart", "hut"],
                        0,
                    ),
                ],
            ),
            (
                "Phỏng vấn xin việc",
                "interview",
                320,
                False,
                [
                    (
                        "Tell me about yourself.",
                        "Hãy giới thiệu về bản thân.",
                        3,
                        ["yourself", "myself", "itself", "herself"],
                        0,
                    ),
                    (
                        "Why do you want this job?",
                        "Tại sao bạn muốn công việc này?",
                        5,
                        ["job", "jog", "joy", "jab"],
                        0,
                    ),
                ],
            ),
        ]
        _listen_colors = {
            "greeting": "#4F46E5",
            "shopping": "#22C55E",
            "travel": "#38BDF8",
            "restaurant": "#FF6B57",
            "interview": "#F59E0B",
        }
        for i, (title_vi, icon, secs, _is_free, items) in enumerate(_listen_sets, start=1):
            lt, _ = ListeningTopic.objects.update_or_create(
                level=a1,
                order=i,
                defaults={
                    "title_vi": title_vi,
                    "icon": icon,
                    "color": _listen_colors.get(icon, ""),
                    "est_seconds": secs,
                    "is_free": True,
                },
            )
            lt.items.all().delete()
            for j, (en, vi, bi, opts, ans) in enumerate(items):
                ListeningItem.objects.create(
                    topic=lt,
                    order=j,
                    text_en=en,
                    text_vi=vi,
                    audio_path=f"audio/listen/{icon}_{j}.mp3",
                    blank_index=bi,
                    options=opts,
                    answer_index=ans,
                )

        # Thư viện bộ thẻ flashcard (C7a) — 3 bộ sưu tập, 6 bộ thẻ, 2 bộ PRO
        _deck_sets = [
            (
                "popular",
                "Bộ sưu tập phổ biến",
                "Thông dụng",
                [
                    (
                        "oxford-3000",
                        "3000 từ Oxford thông dụng",
                        "Oxford 3000",
                        "A1 – B2",
                        True,
                        354_000,
                        "book",
                        "#4F46E5",
                    ),
                    (
                        "ielts-75",
                        "IELTS Speaking & Writing 7.5+",
                        "IELTS Advance",
                        "Band 7.5+",
                        False,
                        198_000,
                        "exam",
                        "",
                    ),
                    (
                        "travel-living",
                        "Từ vựng Du lịch & Đời sống",
                        "Travel & Living",
                        "Thực tế",
                        True,
                        142_000,
                        "travel",
                        "#10B981",
                    ),
                    (
                        "toeic-850",
                        "TOEIC 850+ Cấp Tốc",
                        "TOEIC Master",
                        "850+",
                        False,
                        225_000,
                        "work",
                        "",
                    ),
                ],
            ),
            (
                "oxford",
                "Từ vựng Oxford",
                "Oxford",
                [
                    (
                        "oxford-a1",
                        "Từ vựng Oxford 3000 A1",
                        "Oxford A1",
                        "CEFR A1",
                        True,
                        90_000,
                        "style",
                        "#4F46E5",
                    ),
                    (
                        "oxford-a2",
                        "Từ vựng Oxford 3000 A2",
                        "Oxford A2",
                        "CEFR A2",
                        True,
                        40_000,
                        "style",
                        "#7C3AED",
                    ),
                ],
            ),
        ]
        _all_vocab = list(Vocabulary.objects.order_by("id"))
        for ci, (ccode, ctitle, cchip, decks) in enumerate(_deck_sets, start=1):
            coll, _ = VocabularyDeckCollection.objects.update_or_create(
                code=ccode,
                defaults={"title_vi": ctitle, "chip_label_vi": cchip, "order": ci},
            )
            for di, (dcode, dtitle, cover, badge, is_free, learners, icon, accent) in enumerate(
                decks, start=1
            ):
                deck, _ = VocabularyDeck.objects.update_or_create(
                    code=dcode,
                    defaults={
                        "collection": coll,
                        "title_vi": dtitle,
                        "cover_title": cover,
                        "badge_vi": badge,
                        "background_url": "",
                        "icon": icon,
                        "accent_color": accent,
                        "level": a1,
                        "order": di,
                        "is_free": is_free,
                        "learner_base": learners,
                    },
                )
                deck.items.all().delete()
                for k, v in enumerate(_all_vocab):
                    VocabularyDeckItem.objects.create(deck=deck, vocabulary=v, order=k)

        for i in range(2, 7):  # +5 dialogue → 6  (speaking = 6 + 6 = 12)
            Dialogue.objects.update_or_create(
                title_en=f"Everyday dialogue {i}",
                defaults={
                    "title_vi": f"Hội thoại đời thường {i}",
                    "context_vi": "Luyện phản xạ nói.",
                },
            )
        for i in range(2, 5):  # +3 reading → 4  (reading = 4 + 1 story = 5 "bài mới")
            Reading.objects.update_or_create(
                level=a1,
                order=i,
                defaults={
                    "title_en": f"Short article {i}",
                    "title_vi": f"Bài đọc ngắn {i}",
                    "topic": travel,
                    "est_minutes": 3,
                },
            )

        # Hội thoại AI (hero Trung tâm luyện tập C19)
        RoleplayScenario.objects.update_or_create(
            title_vi="Phỏng vấn xin việc",
            defaults={
                "level": "B1",
                "topic": "Công việc",
                "description_vi": "Phỏng vấn xin việc & thuyết trình chuyên nghiệp",
                "goals": ["Giới thiệu bản thân", "Nói điểm mạnh", "Đặt câu hỏi cho nhà tuyển dụng"],
                "system_prompt": "You are a friendly job interviewer. Ask common interview "
                "questions and give short, encouraging feedback.",
                "is_premium": False,
            },
        )
        RoleplayScenario.objects.update_or_create(
            title_vi="Gọi món tại quán cà phê",
            defaults={
                "level": "A1",
                "topic": "Du lịch",
                "description_vi": "Tập gọi đồ uống và trả tiền tự nhiên",
                "goals": ["Chào hỏi", "Gọi món", "Hỏi giá"],
                "system_prompt": "You are a barista. Help the user order politely in English.",
                "is_premium": False,
            },
        )

        # Tài khoản demo có sẵn tiến độ để preview Home (demo@sayfully.app / demo1234)
        demo, created = User.objects.get_or_create(
            email="demo@sayfully.app", defaults={"full_name": "Quyền Ngọc"}
        )
        if created:
            demo.set_password("demo1234")
        demo.full_name = "Quyền Ngọc"
        demo.save()
        p = ensure_profile(demo)
        p.cefr_level = "A1"
        p.goal_level = "B1"
        p.learning_goal = LearningGoal.DAILY
        p.onboarding_completed = True
        p.onboarding_completed_at = djtz.now()
        p.level = 4
        p.xp_total = 1240
        p.coins = 520
        p.hearts = 5
        p.streak_current = 4
        p.streak_best = 7
        p.daily_goal_words = 20
        p.daily_goal_xp = 150
        p.save()

        today = local_today(p)
        # chuỗi 4 ngày + hoạt động hôm nay khớp "Mục tiêu hôm nay" (120/18/12)
        for i, (xp_v, w_v, m_v, sp_v) in enumerate(
            [(120, 18, 15, 12), (90, 12, 10, 6), (70, 10, 8, 4), (60, 8, 7, 3)]
        ):
            DailyActivity.objects.update_or_create(
                user=demo,
                date=today - timedelta(days=i),
                defaults={
                    "words_reviewed": w_v,
                    "minutes": m_v,
                    "xp": xp_v,
                    "lessons_completed": 1 if i == 0 else 0,
                    "speaking_count": sp_v,
                },
            )
        for completed_lesson in (lesson, lesson2):
            LessonProgress.objects.update_or_create(
                user=demo,
                lesson=completed_lesson,
                defaults={
                    "status": LessonProgress.Status.COMPLETED,
                    "step_index": 0,
                    "stars": 3,
                    "xp_earned": completed_lesson.xp_reward,
                    "completed_at": djtz.now(),
                },
            )
        LessonProgress.objects.update_or_create(
            user=demo,
            lesson=lesson3,
            defaults={"status": LessonProgress.Status.IN_PROGRESS, "step_index": 2},
        )
        # Tiến độ luyện nói theo chủ đề (C8a): đã nói 2/4 câu chủ đề "Chào hỏi"
        _greet_deck = ShadowingDeck.objects.filter(level=a1, order=1).first()
        if _greet_deck:
            SpeakingTopicProgress.objects.update_or_create(
                user=demo,
                deck=_greet_deck,
                defaults={"done_count": 2},
            )
        # Tiến độ luyện nghe (C9a) mode "choose": Chào hỏi 2 câu, Mua sắm đủ (đạt điểm tối đa),
        # Du lịch mới 1 câu
        for order, done in [(1, 2), (2, 3), (3, 1)]:
            lt = ListeningTopic.objects.filter(level=a1, order=order).first()
            if lt:
                ListeningTopicProgress.objects.update_or_create(
                    user=demo,
                    topic=lt,
                    mode=ListeningTopicProgress.Mode.CHOOSE,
                    defaults={"done_count": done},
                )
        LessonProgress.objects.filter(
            user=demo,
            lesson__unit=unit,
            lesson__order__gt=3,
        ).delete()
        for index, vocab in enumerate(Vocabulary.objects.filter(level=a1).order_by("headword")):
            SRSCard.objects.update_or_create(
                user=demo,
                vocabulary=vocab,
                defaults={
                    "state": SRSCard.State.LEARNING,
                    "due_at": djtz.now() - timedelta(minutes=index + 1),
                },
            )
        for code, progress, claimed in (
            ("daily_xp", 120, True),
            ("daily_words", 18, False),
            ("daily_speak", 12, False),
        ):
            UserChallenge.objects.update_or_create(
                user=demo,
                challenge=Challenge.objects.get(code=code),
                period_key=today.isoformat(),
                defaults={
                    "progress": progress,
                    "completed_at": djtz.now() if claimed else None,
                    "claimed_at": djtz.now() if claimed else None,
                },
            )
        if not Notification.objects.filter(user=demo).exists():
            for title in (
                "Chào mừng đến EnGo!",
                "Bạn có 14 từ đến hạn ôn",
                "Chuỗi 4 ngày — giữ vững nhé!",
            ):
                Notification.objects.create(
                    user=demo, kind=Notification.Kind.SYSTEM, title_vi=title
                )

        # Lộ trình B1 (mục tiêu) + tiến độ demo 13/20 = 65% cho màn Hồ sơ
        b1 = Level.objects.get(code="B1")
        b1_lessons = []
        for ui in range(1, 5):
            b1u, _ = Unit.objects.update_or_create(
                level=b1,
                order=ui,
                defaults={
                    "code": f"b1-u{ui}",
                    "title_vi": f"Chủ đề B1 · {ui}",
                    "title_en": f"B1 Topic {ui}",
                    "subtitle": "Giao tiếp tự tin",
                    "description_vi": "Nội dung trình độ B1.",
                    "reward": {"coins": 200},
                },
            )
            for li in range(1, 6):
                bl, _ = Lesson.objects.update_or_create(
                    unit=b1u,
                    order=li,
                    defaults={
                        "code": f"b1-u{ui}-l{li}",
                        "title_vi": f"Bài {li}",
                        "title_en": f"Lesson {li}",
                        "description_vi": "Bài học B1.",
                        "path_subtitle_vi": "Luyện tập giao tiếp trình độ B1",
                        "est_minutes": 12,
                        "xp_reward": 60,
                    },
                )
                b1_lessons.append(bl)
        for bl in b1_lessons[:13]:
            LessonProgress.objects.update_or_create(
                user=demo,
                lesson=bl,
                defaults={
                    "status": LessonProgress.Status.COMPLETED,
                    "step_index": 0,
                    "stars": 3,
                    "xp_earned": bl.xp_reward,
                    "completed_at": djtz.now(),
                },
            )
        for bl in b1_lessons[13:]:
            LessonProgress.objects.filter(user=demo, lesson=bl).delete()

        # Liên đoàn Kim cương — demo đứng hạng #4
        iso = djtz.now().isocalendar()
        iso_year, iso_week = iso[0], iso[1]
        LeagueMembership.objects.filter(
            user=demo, group__iso_year=iso_year, group__iso_week=iso_week
        ).delete()
        dgroup, _ = LeagueGroup.objects.get_or_create(
            tier=LeagueGroup.Tier.DIAMOND, iso_year=iso_year, iso_week=iso_week
        )
        rivals = [
            ("linh.tran@demo.engo", "Linh Trần", 2450),
            ("minh.pham@demo.engo", "Minh Phạm", 1980),
            ("an.nguyen@demo.engo", "An Nguyễn", 1600),
            ("hoa.le@demo.engo", "Hoa Lê", 900),
            ("nam.vo@demo.engo", "Nam Võ", 700),
        ]
        demo_week_xp = 1420  # dưới 3 người đầu → hạng 4; 1420/1800 = 78.8%
        for email, name, xp in rivals:
            r, rc = User.objects.get_or_create(email=email, defaults={"full_name": name})
            if rc:
                r.set_unusable_password()
                r.save()
            ensure_profile(r)
            LeagueMembership.objects.update_or_create(
                group=dgroup, user=r, defaults={"xp_week": xp}
            )
            WeeklyStat.objects.update_or_create(
                user=r, iso_year=iso_year, iso_week=iso_week, defaults={"xp": xp}
            )
        # đệm nhóm ~82 người (đều dưới demo) để hạng 4 ≈ Top 5%
        for i in range(76):
            fr, frc = User.objects.get_or_create(
                email=f"member{i:02d}@demo.engo", defaults={"full_name": f"Học viên {i + 1}"}
            )
            if frc:
                fr.set_unusable_password()
                fr.save()
            ensure_profile(fr)
            fxp = 100 + (i * 17) % 1300  # 100..1399, luôn dưới demo
            LeagueMembership.objects.update_or_create(
                group=dgroup, user=fr, defaults={"xp_week": fxp}
            )
            WeeklyStat.objects.update_or_create(
                user=fr, iso_year=iso_year, iso_week=iso_week, defaults={"xp": fxp}
            )
        LeagueMembership.objects.update_or_create(
            group=dgroup, user=demo, defaults={"xp_week": demo_week_xp}
        )
        WeeklyStat.objects.update_or_create(
            user=demo, iso_year=iso_year, iso_week=iso_week, defaults={"xp": demo_week_xp}
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Xong. Levels={Level.objects.count()} Vocab={Vocabulary.objects.count()} "
                f"Lessons={Lesson.objects.count()} Challenges={Challenge.objects.count()} "
                f"Shop={ShopItem.objects.count()} Products={Product.objects.count()} "
                f"Demo=demo@sayfully.app/demo1234"
            )
        )
