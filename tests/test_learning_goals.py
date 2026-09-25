"""Gợi ý nội dung theo mục tiêu học trong hồ sơ: bộ thẻ, chủ đề video, kịch bản Gia sư AI."""

import pytest

from apps.accounts.services import ensure_profile
from apps.ai.management.commands.seed_scenarios import seed_roleplay_scenarios
from apps.ai.models import RoleplayScenario
from apps.common.learning_goals import deck_goals, parse_goals, scenario_goals, video_category_goals
from apps.content.models import Video, VideoCategory, VocabularyDeck, VocabularyDeckCollection

pytestmark = pytest.mark.django_db


@pytest.fixture
def token(api, user, password) -> str:
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


def _goal(user, goal: str):
    profile = ensure_profile(user)
    profile.learning_goal = goal
    profile.save(update_fields=["learning_goal"])


def test_doc_muc_tieu_nhan_ca_ma_lan_nhan_tieng_viet():
    assert parse_goals("ielts, Du lịch khám phá; lạ") == ["ielts", "travel"]
    assert parse_goals("") == []


def test_quy_tac_mac_dinh_khi_sheet_de_trong():
    assert deck_goals("ielts-band-6-7") == ["ielts"]
    assert deck_goals("ets-toeic") == ["toeic"]
    assert deck_goals("oxford-3000-b2") == []
    assert video_category_goals("", "Điện ảnh & Hoạt hình Đỉnh cao") == ["media", "kids"]
    assert video_category_goals("business-workplace") == ["toeic"]
    assert scenario_goals("airport", "Du lịch") == ["travel"]
    assert scenario_goals("interview", "Công việc") == ["toeic"]


def test_thu_vien_the_goi_y_bo_hop_muc_tieu(api, token, user):
    _goal(user, "ielts")
    collection = VocabularyDeckCollection.objects.create(code="exam", title_vi="Luyện thi", order=1)
    for i, (code, goals) in enumerate([("toeic-600", ["toeic"]), ("ielts-600", ["ielts"]), ("ielts-idioms", ["ielts"])]):
        VocabularyDeck.objects.create(collection=collection, code=code, title_vi=code, order=i, learning_goals=goals)

    body = api.get("/learn/flashcard/decks", token=token).json()

    assert body["learning_goal"] == "ielts"
    assert [d["code"] for d in body["suggested"]] == ["ielts-600", "ielts-idioms"]
    assert len(body["collections"][0]["decks"]) == 3  # gợi ý không lấy bớt bộ nào khỏi thư viện


def test_thu_vien_the_khong_goi_y_khi_khong_bo_nao_khop(api, token, user):
    _goal(user, "kids")
    collection = VocabularyDeckCollection.objects.create(code="exam", title_vi="Luyện thi", order=1)
    VocabularyDeck.objects.create(collection=collection, code="toeic-600", title_vi="TOEIC", learning_goals=["toeic"])

    assert api.get("/learn/flashcard/decks", token=token).json()["suggested"] == []


def test_video_xep_chu_de_hop_muc_tieu_len_truoc(api, token, user):
    _goal(user, "media")
    VideoCategory.objects.create(name="Giao tiếp", order=1, learning_goals=["daily"])
    VideoCategory.objects.create(name="Điện ảnh", order=2, learning_goals=["media"])
    Video.objects.create(youtube_id="a1", title_vi="A", title_en="A", category="Giao tiếp", is_featured=True)
    Video.objects.create(youtube_id="b1", title_vi="B", title_en="B", category="Điện ảnh")
    Video.objects.create(youtube_id="b2", title_vi="B2", title_en="B2", category="Điện ảnh")

    items = api.get("/content/videos?limit=10", token=token).json()["items"]

    assert [v["category"] for v in items] == ["Điện ảnh", "Điện ảnh", "Giao tiếp"]


def test_video_giu_thu_tu_cu_khi_muc_tieu_khong_co_chu_de(api, token, user):
    _goal(user, "kids")
    VideoCategory.objects.create(name="Giao tiếp", order=1, learning_goals=["daily"])
    Video.objects.create(youtube_id="a1", title_vi="A", title_en="A", category="Giao tiếp")
    Video.objects.create(youtube_id="f1", title_vi="F", title_en="F", category="Khác", is_featured=True)

    items = api.get("/content/videos?limit=10", token=token).json()["items"]

    assert [v["youtube_id"] for v in items] == ["f1", "a1"]


def test_seed_kich_ban_gan_muc_tieu_theo_boi_canh():
    seed_roleplay_scenarios()
    airport = RoleplayScenario.objects.get(scene="airport")
    assert airport.learning_goals == ["travel"]


def test_hub_gia_su_goi_y_kich_ban_hop_muc_tieu(api, token, user, settings):
    settings.AI_ENABLED = True
    settings.AI_PROVIDER = "mock"
    seed_roleplay_scenarios()
    _goal(user, "travel")

    body = api.get("/ai/home", token=token).json()

    assert body["learning_goal"] == "travel"
    assert 0 < len(body["suggested"]) <= 3
    ids = {sc.id for sc in RoleplayScenario.objects.all() if "travel" in sc.learning_goals}
    assert all(sc["id"] in ids for sc in body["suggested"])
    assert body["suggested"][0]["level"] == "A1"  # hồ sơ mặc định A1: cấp gần nhất lên trước
