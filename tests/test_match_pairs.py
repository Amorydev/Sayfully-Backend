"""Ghép cặp — nội dung chặng, ván chơi, kết quả."""

import pytest

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
def test_difficulty_pair_counts():
    from apps.gamification.models import MatchPairsProgress as P

    assert P.pairs_for(P.Difficulty.EASY) == 6
    assert P.pairs_for(P.Difficulty.MEDIUM) == 8
    assert P.pairs_for(P.Difficulty.HARD) == 10
    assert P.pairs_for(P.Difficulty.EXPERT) == 12


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
