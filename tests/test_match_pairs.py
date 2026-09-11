"""Ghép cặp — nội dung chặng, ván chơi, kết quả."""

import copy

import pytest
from django.db import transaction
from django.db.utils import IntegrityError
from django.test import RequestFactory

from apps.gamification.admin import MatchPairsStageAdmin
from apps.gamification.models import MatchPairsStage, MatchPairsWord


def _stage(code="the-gioi-quanh-ta", order=0, words=12, level="A1"):
    stage = MatchPairsStage.objects.create(
        code=code,
        title_vi="Thế giới quanh ta",
        subtitle_vi="Những từ quen thuộc mỗi ngày",
        symbol="✦",
        level=level,
        order=order,
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
    assert stage.is_playable is True


@pytest.mark.django_db
def test_stage_thieu_tu_thi_khong_choi_duoc():
    stage = _stage(code="thieu", words=5)
    assert stage.is_playable is False


@pytest.mark.django_db
def test_stage_11_tu_van_khong_choi_duoc():
    """Biên ngay dưới MIN_PAIRS: 11 chưa đủ, phải là False."""
    stage = _stage(code="muoimot", words=11)
    assert stage.is_playable is False


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
