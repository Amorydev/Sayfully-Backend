"""Ghép cặp — nội dung chặng, ván chơi, kết quả."""

import copy

import pytest
from django.db import transaction
from django.db.utils import IntegrityError
from django.test import RequestFactory

from apps.gamification.admin import MatchPairsStageAdmin
from apps.gamification.models import MatchPairsStage, MatchPairsWord


@pytest.fixture
def token(api, user, password):
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


def _stage(code="the-gioi-quanh-ta", order=0, words=12, level="A1", is_active=True):
    stage = MatchPairsStage.objects.create(
        code=code,
        title_vi="Thế giới quanh ta",
        subtitle_vi="Những từ quen thuộc mỗi ngày",
        symbol="✦",
        level=level,
        order=order,
        is_active=is_active,
    )
    for i in range(words):
        MatchPairsWord.objects.create(
            stage=stage, order=i, english=f"{code}-en-{i}", vietnamese=f"{code}-vi-{i}"
        )
    return stage


@pytest.mark.django_db
def test_stage_pair_count():
    stage = _stage()
    assert stage.pairs.count() == 12
    assert MatchPairsStage.objects.playable().filter(pk=stage.pk).exists() is True


@pytest.mark.django_db
def test_stage_thieu_tu_thi_khong_choi_duoc():
    stage = _stage(code="thieu", words=5)
    assert MatchPairsStage.objects.playable().filter(pk=stage.pk).exists() is False


@pytest.mark.django_db
def test_stage_11_tu_van_khong_choi_duoc():
    """Biên ngay dưới MIN_PAIRS: 11 chưa đủ, phải là False."""
    stage = _stage(code="muoimot", words=11)
    assert MatchPairsStage.objects.playable().filter(pk=stage.pk).exists() is False


def test_difficulty_pair_counts():
    from apps.gamification.models import MatchPairsProgress as P

    assert P.pairs_for(P.Difficulty.EASY) == 6
    assert P.pairs_for(P.Difficulty.MEDIUM) == 8
    assert P.pairs_for(P.Difficulty.HARD) == 10
    assert P.pairs_for(P.Difficulty.EXPERT) == 12


def test_pairs_dinh_nghia_du_cho_moi_do_kho():
    """Thêm độ khó mà quên số cặp sẽ làm 500 màn bản đồ, nên chốt ở đây."""
    from apps.gamification.models import MatchPairsProgress as P

    assert set(P._PAIRS) == set(P.Difficulty.values)


def test_chang_du_cap_cho_do_kho_cao_nhat():
    """random.sample sẽ nổ nếu độ khó cao nhất cần nhiều cặp hơn ngưỡng chặng."""
    from apps.gamification.models import MatchPairsProgress as P

    assert MatchPairsStage.MIN_PAIRS >= max(P._PAIRS.values())


@pytest.mark.django_db
@pytest.mark.parametrize(
    "difficulty,moves,expected",
    [
        ("easy", 8, 3), ("easy", 11, 2), ("easy", 12, 1),
        ("medium", 10, 3), ("medium", 14, 2), ("medium", 15, 1),
        ("hard", 13, 3), ("hard", 18, 2), ("hard", 19, 1),
        ("expert", 15, 3), ("expert", 21, 2), ("expert", 22, 1),
    ],
)
def test_stars_for(difficulty, moves, expected):
    from apps.gamification.models import MatchPairsProgress as P

    assert P.stars_for(difficulty, moves) == expected


@pytest.mark.django_db
def test_trung_english_trong_chang_bi_chan():
    """Hai thẻ tiếng Anh giống nhau trong cùng chặng làm ván không thể thắng."""
    stage = _stage(code="trung-en", words=1)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MatchPairsWord.objects.create(
                stage=stage, order=1, english="trung-en-en-0", vietnamese="nghia-khac"
            )


@pytest.mark.django_db
def test_trung_vietnamese_trong_chang_bi_chan():
    """Hai thẻ nghĩa tiếng Việt giống nhau trong cùng chặng làm ván không thể thắng."""
    stage = _stage(code="trung-vi", words=1)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MatchPairsWord.objects.create(
                stage=stage, order=1, english="tu-khac", vietnamese="trung-vi-vi-0"
            )


@pytest.mark.django_db
def test_trung_tu_o_chang_khac_duoc_phep():
    """Ràng buộc chỉ chặn trùng trong cùng chặng, không chặn qua chặng khác."""
    stage_a = _stage(code="chang-a", words=1)
    stage_b = _stage(code="chang-b", words=0)

    word = MatchPairsWord.objects.create(
        stage=stage_b, order=0, english="chang-a-en-0", vietnamese="chang-a-vi-0"
    )

    assert word.pk is not None
    assert stage_a.pairs.filter(english="chang-a-en-0").exists()
    assert stage_b.pairs.filter(english="chang-a-en-0").exists()


@pytest.mark.django_db
def test_admin_canh_bao_chang_thieu_cap(django_assert_num_queries):
    """Changelist phải cảnh báo chặng thiếu cặp, và đếm đúng cho chặng đủ cặp — qua đúng một truy vấn."""
    from django.contrib import admin as django_admin

    site = django_admin.site
    model_admin = site._registry[MatchPairsStage]
    assert isinstance(model_admin, MatchPairsStageAdmin)

    _stage(code="canh-bao-thieu", words=5)
    _stage(code="canh-bao-du", words=12)

    request = RequestFactory().get("/admin/gamification/matchpairsstage/")
    with django_assert_num_queries(1):
        by_code = {
            obj.code: model_admin.pair_count(obj)
            for obj in model_admin.get_queryset(request).filter(code__startswith="canh-bao-")
        }

    assert by_code["canh-bao-thieu"] == "5 ⚠"
    assert by_code["canh-bao-du"] == 12


@pytest.mark.django_db
def test_trung_user_stage_do_kho_bi_chan(user):
    """(user, stage, difficulty) phải là duy nhất — không thì mất tính năng chỉ nâng sao."""
    from apps.gamification.models import MatchPairsProgress as P

    stage = _stage(code="progress", words=1)
    P.objects.create(user=user, stage=stage, difficulty=P.Difficulty.EASY)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            P.objects.create(user=user, stage=stage, difficulty=P.Difficulty.EASY)


@pytest.mark.django_db
def test_seed_match_pairs_idempotent():
    from django.core.management import call_command

    call_command("seed_match_pairs")
    first = MatchPairsStage.objects.count()
    assert first >= 3
    assert all(s.pairs.count() == 12 for s in MatchPairsStage.objects.all())

    call_command("seed_match_pairs")
    assert MatchPairsStage.objects.count() == first
    assert MatchPairsWord.objects.count() == first * 12


@pytest.mark.django_db
def test_seed_match_pairs_doi_thu_tu_khong_loi(monkeypatch):
    """Đảo thứ tự cặp trong STAGES rồi nạp lại không được vỡ ràng buộc duy nhất."""
    from django.core.management import call_command

    from apps.common.management.commands import seed_match_pairs as cmd

    call_command("seed_match_pairs")
    stage = MatchPairsStage.objects.get(code=cmd.STAGES[0]["code"])
    stage_pk_before = stage.pk

    swapped = copy.deepcopy(cmd.STAGES)
    pairs = swapped[0]["pairs"]
    pairs[0], pairs[1] = pairs[1], pairs[0]
    monkeypatch.setattr(cmd, "STAGES", swapped)

    call_command("seed_match_pairs")  # trước đây: IntegrityError uniq_stage_english

    stage.refresh_from_db()
    assert stage.pk == stage_pk_before
    assert list(stage.pairs.order_by("order").values_list("english", flat=True)[:2]) == [
        pairs[0][0],
        pairs[1][0],
    ]
    assert stage.pairs.count() == 12


@pytest.mark.django_db
def test_stages_chang_dau_mo_khoa(api, token, user):
    _stage(code="s0", order=0)
    _stage(code="s1", order=1)
    body = api.get("/match-pairs/stages", token=token).json()
    assert body["max_stars"] == 24  # 2 chặng × 4 độ khó × 3 sao
    assert body["total_stars"] == 0
    assert [s["code"] for s in body["stages"]] == ["s0", "s1"]
    assert body["stages"][0]["is_unlocked"] is True
    assert body["stages"][1]["is_unlocked"] is False
    assert [d["code"] for d in body["stages"][0]["difficulties"]] == [
        "easy", "medium", "hard", "expert"
    ]
    assert body["stages"][0]["difficulties"][0]["pairs"] == 6
    assert body["stages"][0]["difficulties"][0]["three_star_moves"] == 8


@pytest.mark.django_db
def test_stages_an_chang_thieu_tu(api, token, user):
    _stage(code="du", order=0)
    _stage(code="thieu", order=1, words=4)
    body = api.get("/match-pairs/stages", token=token).json()
    assert [s["code"] for s in body["stages"]] == ["du"]


@pytest.mark.django_db
def test_stages_sao_va_mo_khoa_theo_tien_do(api, token, user):
    from apps.gamification.models import MatchPairsProgress

    s0 = _stage(code="s0", order=0)
    _stage(code="s1", order=1)
    MatchPairsProgress.objects.create(
        user=user, stage=s0, difficulty="easy", stars=3, best_moves=7, play_count=1
    )
    body = api.get("/match-pairs/stages", token=token).json()
    assert body["total_stars"] == 3
    assert body["stages"][0]["stars"] == 3
    assert body["stages"][0]["is_completed"] is True
    assert body["stages"][0]["difficulties"][0]["stars"] == 3
    assert body["stages"][0]["difficulties"][0]["best_moves"] == 7
    assert body["stages"][1]["is_unlocked"] is True


@pytest.mark.django_db
def test_stages_can_dang_nhap():
    from django.test import Client

    r = Client().get("/api/v1/match-pairs/stages")
    assert r.status_code == 401


@pytest.mark.django_db
def test_stages_dong_0_sao_van_hoan_thanh(api, token, user):
    """Dòng tiến độ 0 sao (vd. admin tạo tay) vẫn tính là đã chơi: hoàn thành = có dòng, không phải có sao."""
    from apps.gamification.models import MatchPairsProgress

    s0 = _stage(code="s0", order=0)
    _stage(code="s1", order=1)
    MatchPairsProgress.objects.create(
        user=user, stage=s0, difficulty="easy", stars=0, best_moves=0, play_count=0
    )
    body = api.get("/match-pairs/stages", token=token).json()
    assert body["stages"][0]["is_completed"] is True
    assert body["stages"][1]["is_unlocked"] is True
    assert body["total_stars"] == 0


@pytest.mark.django_db
def test_stages_chang_tat_bi_an_va_chuoi_noi_qua(api, token, user):
    """Chặng tắt hoặc thiếu cặp bị ẩn khỏi bản đồ; chuỗi mở khoá chỉ nối các chặng còn hiển thị."""
    from apps.gamification.models import MatchPairsProgress

    s0 = _stage(code="s0", order=0)
    _stage(code="h1", order=1, is_active=False)
    _stage(code="h2", order=2, words=4)
    _stage(code="s3", order=3)
    MatchPairsProgress.objects.create(
        user=user, stage=s0, difficulty="easy", stars=3, best_moves=7, play_count=1
    )
    body = api.get("/match-pairs/stages", token=token).json()
    assert [st["code"] for st in body["stages"]] == ["s0", "s3"]
    assert body["stages"][1]["is_unlocked"] is True


@pytest.mark.django_db
def test_stages_da_choi_thi_luon_mo(api, token, user):
    """Chặng đã có dòng tiến độ luôn mở, kể cả khi chặng liền trước nó chưa hoàn thành."""
    from apps.gamification.models import MatchPairsProgress

    _stage(code="s0", order=0)
    s1 = _stage(code="s1", order=1)
    _stage(code="s2", order=2)
    MatchPairsProgress.objects.create(
        user=user, stage=s1, difficulty="easy", stars=2, best_moves=10, play_count=1
    )
    body = api.get("/match-pairs/stages", token=token).json()
    assert body["stages"][0]["is_unlocked"] is True
    assert body["stages"][1]["is_unlocked"] is True
    assert body["stages"][2]["is_unlocked"] is True


@pytest.mark.django_db
def test_playable_stages_mot_truy_van(django_assert_num_queries):
    """`_playable_stages` chạy đúng một truy vấn và không kéo từ nào của chặng về."""
    from apps.gamification.api import _playable_stages

    _stage(code="p0", order=0)
    _stage(code="p1", order=1)
    _stage(code="p2", order=2)
    _stage(code="thieu", order=3, words=4)

    with django_assert_num_queries(1):
        stages = _playable_stages()

    assert len(stages) == 3
    if hasattr(stages[0], "_prefetched_objects_cache"):
        assert "pairs" not in stages[0]._prefetched_objects_cache
    else:
        assert not hasattr(stages[0], "_prefetched_objects_cache")


def test_thresholds_for_khop_stars_for():
    """`thresholds_for` phải khớp đúng các mốc mà `stars_for` dùng để chấm sao."""
    from apps.gamification.models import MatchPairsProgress as P

    for d in P.Difficulty.values:
        three, two = P.thresholds_for(d)
        assert P.stars_for(d, three) == 3
        assert P.stars_for(d, three + 1) == 2
        assert P.stars_for(d, two) == 2
        assert P.stars_for(d, two + 1) == 1

    assert P.thresholds_for("expert") == (15, 21)


@pytest.mark.django_db
def test_round_tra_dung_so_cap(api, token, user):
    stage = _stage()
    body = api.get(f"/match-pairs/stages/{stage.id}/round?difficulty=easy", token=token).json()
    assert body["stage_id"] == stage.id and body["difficulty"] == "easy"
    assert len(body["pairs"]) == 6
    assert body["three_star_moves"] == 8 and body["two_star_moves"] == 11


@pytest.mark.django_db
def test_round_cac_cap_phan_biet(api, token, user):
    """Bắt rút *có* hoàn lại (choices thay vì sample): 12 lấy 12 mà trùng là hỏng."""
    stage = _stage()
    body = api.get(f"/match-pairs/stages/{stage.id}/round?difficulty=expert", token=token).json()
    english = [p["english"] for p in body["pairs"]]
    vietnamese = [p["vietnamese"] for p in body["pairs"]]
    assert len(set(english)) == 12 and len(set(vietnamese)) == 12


@pytest.mark.django_db
def test_round_doi_cap_moi_lan_goi(api, token, user):
    """Chơi lại Dễ phải gặp từ khác, nếu không chặng chỉ dạy được sáu từ đầu."""
    stage = _stage()
    seen = set()
    for _ in range(12):
        body = api.get(
            f"/match-pairs/stages/{stage.id}/round?difficulty=easy", token=token
        ).json()
        seen.add(tuple(sorted(p["english"] for p in body["pairs"])))
    assert len(seen) > 1


@pytest.mark.django_db
def test_round_do_kho_sai_422(api, token, user):
    stage = _stage()
    r = api.get(f"/match-pairs/stages/{stage.id}/round?difficulty=sieu-kho", token=token)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_difficulty"


@pytest.mark.django_db
def test_round_chang_khong_ton_tai_404(api, token, user):
    assert api.get("/match-pairs/stages/9999/round?difficulty=easy", token=token).status_code == 404


@pytest.mark.django_db
def test_round_chang_bi_khoa_403(api, token, user):
    _stage(code="s0", order=0)
    locked = _stage(code="s1", order=1)
    r = api.get(f"/match-pairs/stages/{locked.id}/round?difficulty=easy", token=token)
    assert r.status_code == 403 and r.json()["error"]["code"] == "stage_locked"


@pytest.mark.django_db
def test_round_da_choi_thi_luon_mo(api, token, user):
    """Chặng đã có dòng tiến độ luôn mở cho ván mới, kể cả khi chặng liền trước chưa hoàn thành."""
    from apps.gamification.models import MatchPairsProgress

    s0 = _stage(code="s0", order=0)
    s1 = _stage(code="s1", order=1)
    s2 = _stage(code="s2", order=2)
    MatchPairsProgress.objects.create(
        user=user, stage=s1, difficulty="easy", stars=1, best_moves=9, play_count=1
    )
    assert (
        api.get(f"/match-pairs/stages/{s1.id}/round?difficulty=easy", token=token).status_code
        == 200
    )
    assert (
        api.get(f"/match-pairs/stages/{s2.id}/round?difficulty=easy", token=token).status_code
        == 200
    )
    assert (
        api.get(f"/match-pairs/stages/{s0.id}/round?difficulty=easy", token=token).status_code
        == 200
    )


@pytest.mark.django_db
def test_round_chang_thieu_cap_404(api, token, user):
    """Chặng chưa đủ cặp bị ẩn khỏi danh sách chơi được: guard `random.sample` khỏi bao giờ nổ."""
    stage = _stage(words=11)
    r = api.get(f"/match-pairs/stages/{stage.id}/round?difficulty=expert", token=token)
    assert r.status_code == 404


def _match_pairs_game():
    from apps.gamification.models import Game

    return Game.objects.create(
        code="match_pairs", title_vi="Ghép cặp", description_vi="x", kind="memory"
    )


@pytest.mark.django_db
def test_result_tinh_sao_va_thuong(api, token, user):
    _match_pairs_game()
    stage = _stage()
    body = api.post(
        f"/match-pairs/stages/{stage.id}/result",
        {"difficulty": "easy", "moves": 7, "duration_sec": 40},
        token=token,
    ).json()
    assert body["stars"] == 3 and body["best_stars"] == 3 and body["best_moves"] == 7
    assert body["coins_earned"] > 0 and body["xp_earned"] > 0
    user.profile.refresh_from_db()
    assert user.profile.coins == body["coins_earned"]


@pytest.mark.django_db
def test_result_chi_nang_khong_ha(api, token, user):
    _match_pairs_game()
    stage = _stage()
    api.post(
        f"/match-pairs/stages/{stage.id}/result", {"difficulty": "easy", "moves": 7}, token=token
    )
    body = api.post(
        f"/match-pairs/stages/{stage.id}/result", {"difficulty": "easy", "moves": 30}, token=token
    ).json()
    assert body["stars"] == 1 and body["best_stars"] == 3 and body["best_moves"] == 7


@pytest.mark.django_db
def test_result_mo_khoa_chang_ke(api, token, user):
    _match_pairs_game()
    s0 = _stage(code="s0", order=0)
    s1 = _stage(code="s1", order=1)
    body = api.post(
        f"/match-pairs/stages/{s0.id}/result", {"difficulty": "easy", "moves": 7}, token=token
    ).json()
    assert body["unlocked_stage_id"] == s1.id


@pytest.mark.django_db
def test_result_choi_lai_khong_bao_mo_khoa_nua(api, token, user):
    """Mở khoá chỉ xảy ra một lần; chơi lại không được báo mở khoá lần hai."""
    _match_pairs_game()
    s0 = _stage(code="s0", order=0)
    _stage(code="s1", order=1)
    api.post(
        f"/match-pairs/stages/{s0.id}/result", {"difficulty": "easy", "moves": 7}, token=token
    )
    body = api.post(
        f"/match-pairs/stages/{s0.id}/result", {"difficulty": "hard", "moves": 13}, token=token
    ).json()
    assert body["unlocked_stage_id"] is None


@pytest.mark.django_db
def test_result_khong_bao_mo_khoa_chang_ke_da_choi(api, token, user):
    """Chặng kế đã có dòng tiến độ riêng (đã mở từ trước) thì không báo mở khoá lại."""
    from apps.gamification.models import MatchPairsProgress

    _match_pairs_game()
    s0 = _stage(code="s0", order=0)
    s1 = _stage(code="s1", order=1)
    MatchPairsProgress.objects.create(
        user=user, stage=s1, difficulty="easy", stars=1, best_moves=9, play_count=1
    )
    body = api.post(
        f"/match-pairs/stages/{s0.id}/result", {"difficulty": "easy", "moves": 7}, token=token
    ).json()
    assert body["unlocked_stage_id"] is None


@pytest.mark.django_db
def test_result_ghi_gamescore_cho_bang_xep_hang(api, token, user):
    from apps.gamification.models import GameScore

    _match_pairs_game()
    stage = _stage()
    api.post(
        f"/match-pairs/stages/{stage.id}/result", {"difficulty": "expert", "moves": 15}, token=token
    )
    assert GameScore.objects.filter(user=user, game__code="match_pairs").count() == 1


@pytest.mark.django_db
def test_result_so_luot_vo_ly_422(api, token, user):
    _match_pairs_game()
    stage = _stage()
    r = api.post(
        f"/match-pairs/stages/{stage.id}/result", {"difficulty": "easy", "moves": 3}, token=token
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_moves"


@pytest.mark.django_db
def test_result_so_luot_qua_tran_422(api, token, user):
    """40000 lượt vượt trần smallint của cột best_moves — phải bị chặn trước khi chạm DB
    ở ván đầu tiên (get_or_create defaults ghi thẳng payload.moves), không để DataError 500."""
    from apps.gamification.models import MatchPairsProgress

    _match_pairs_game()
    stage = _stage()
    r = api.post(
        f"/match-pairs/stages/{stage.id}/result",
        {"difficulty": "easy", "moves": 40000},
        token=token,
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_moves"
    assert not MatchPairsProgress.objects.exists()
    assert user.profile.coins == 0


@pytest.mark.django_db
def test_result_dung_bang_so_cap_la_van_hoan_hao(api, token, user):
    """moves == pairs là mức tối thiểu còn hợp lệ — vẫn phải chấm hoàn hảo (3 sao)."""
    _match_pairs_game()
    stage = _stage()
    body = api.post(
        f"/match-pairs/stages/{stage.id}/result", {"difficulty": "easy", "moves": 6}, token=token
    ).json()
    assert body["stars"] == 3 and body["best_moves"] == 6


@pytest.mark.django_db
def test_result_dong_admin_0_luot_lay_luot_cua_van_dau(api, token, user):
    """Dòng tiến độ do admin tạo tay có best_moves=0 (falsy) — lượt của ván đầu tiên phải
    được lấy thẳng, không rơi vào min(0, moves) == 0."""
    from apps.gamification.models import MatchPairsProgress

    _match_pairs_game()
    stage = _stage()
    MatchPairsProgress.objects.create(
        user=user, stage=stage, difficulty="easy", stars=0, best_moves=0, play_count=0
    )
    body = api.post(
        f"/match-pairs/stages/{stage.id}/result", {"difficulty": "easy", "moves": 9}, token=token
    ).json()
    assert body["best_moves"] == 9 and body["stars"] == 2 and body["best_stars"] == 2
    row = MatchPairsProgress.objects.get(user=user, stage=stage, difficulty="easy")
    assert row.play_count == 1


@pytest.mark.django_db
def test_bang_xep_hang_hoa_diem_thu_tu_on_dinh(api, token, user):
    """Ba người hoà điểm — điểm Ghép cặp chỉ có 12 giá trị nên hoà là chuyện thường. Thử lại
    với chỉ order_by("-best") thì cả 10 lần gọi trên Postgres vẫn tình cờ ra cùng một thứ tự
    (bảng có 3 dòng, quá ít để lộ tính vô định của DB), nên bài test không chỉ đòi "ổn định"
    mà ghim đúng luật đã chọn: sắp theo -best rồi user_id tăng dần — đúng thứ tự sinh ra bởi
    order_by("-best", "user_id")."""
    from apps.accounts.models import User
    from apps.gamification.models import Game, GameScore

    _match_pairs_game()
    game = Game.objects.get(code="match_pairs")
    other1 = User.objects.create_user(email="hoa1@example.com", full_name="Người Hoà Một")
    other2 = User.objects.create_user(email="hoa2@example.com", full_name="Người Hoà Hai")
    for u in (user, other1, other2):
        GameScore.objects.create(
            user=u, game=game, level="A1", score=1800, accuracy=0.5, coins_earned=5
        )
    by_user_id = sorted([user, other1, other2], key=lambda u: u.id)
    expected_names = [u.full_name for u in by_user_id]
    expected_rank = by_user_id.index(user) + 1

    calls = [api.get("/games/leaderboard?code=match_pairs", token=token).json() for _ in range(3)]
    for body in calls:
        assert [e["name"] for e in body["entries"]] == expected_names
        assert body["my_rank"] == expected_rank
