import json

import pytest
from django.core.management import call_command

from apps.gamification.avatar_frames import AVATAR_FRAMES, seed_avatar_frames
from apps.gamification.models import ShopItem, UserCosmetic

pytestmark = pytest.mark.django_db


def test_catalog_command_is_idempotent_and_preserves_existing_products(user):
    call_command("seed_avatar_frames")
    ids = dict(ShopItem.objects.values_list("code", "id"))
    assert len(ids) == 12
    assert ShopItem.objects.filter(meta__animated=True).count() == 8
    frame = ShopItem.objects.get(code="frame_neon")
    frame.cost_coins = 42
    frame.is_active = False
    frame.discount_pct = 10
    frame.save()
    UserCosmetic.objects.create(user=user, item=frame)
    call_command("seed_avatar_frames")
    assert dict(ShopItem.objects.values_list("code", "id")) == ids
    frame.refresh_from_db()
    assert (frame.cost_coins, frame.is_active, frame.discount_pct) == (42, False, 10)
    assert UserCosmetic.objects.filter(user=user, item=frame).exists()


@pytest.mark.parametrize("code", [row[0] for row in AVATAR_FRAMES])
def test_frame_purchase_equip_and_all_profile_apis(api, client, user, password, code):
    seed_avatar_frames()
    token = api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]
    profile = user.profile
    profile.coins = 10000
    profile.save()
    items = api.get("/shop/items", token=token)
    assert items.status_code == 200
    assert len([item for item in items.json() if item["category"] == "cosmetic"]) == 12
    frame = ShopItem.objects.get(code=code)
    denied = api.post("/shop/cosmetics/equip", {"item_id": frame.id}, token=token)
    assert denied.status_code == 409
    purchase = client.post(
        "/api/v1/shop/purchase",
        data=json.dumps({"item_id": frame.id}),
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"test-{code}"},
    )
    assert purchase.status_code == 200
    assert api.post("/shop/cosmetics/equip", {"item_id": frame.id}, token=token).status_code == 200
    for path, nested in (
        ("/home", "profile"),
        ("/profile/overview", None),
        ("/auth/me", "profile"),
    ):
        response = api.get(path, token=token)
        assert response.status_code == 200
        body = response.json()[nested] if nested else response.json()
        assert body["avatar_frame"] == code
        assert body["avatar_frame_colors"] == frame.meta["colors"]
    assert api.post("/shop/cosmetics/equip", {"item_id": None}, token=token).status_code == 200
    assert api.get("/home", token=token).json()["profile"]["avatar_frame"] is None
    assert api.get("/profile/overview", token=token).json()["avatar_frame"] is None


def test_catalog_rejects_code_collision_without_partial_writes():
    ShopItem.objects.create(code="frame_dragon", title_vi="Other", cost_coins=1)
    with pytest.raises(ValueError, match="non-cosmetic"):
        seed_avatar_frames()
    assert ShopItem.objects.count() == 1


def test_leaderboard_entries_carry_each_players_equipped_frame(api, user, password):
    from apps.accounts.models import User
    from apps.gamification.services import current_week, ensure_league_membership
    from apps.learning.models import WeeklyStat

    seed_avatar_frames()
    dragon = ShopItem.objects.get(code="frame_dragon")
    rival = User.objects.create_user(
        email="rival@example.com", password=password, full_name="Đối Thủ"
    )
    UserCosmetic.objects.create(user=rival, item=dragon)
    rival.profile.avatar_frame = dragon.code
    rival.profile.xp_total = 900
    rival.profile.save()
    user.profile.xp_total = 100
    user.profile.save()
    y, w = current_week()
    WeeklyStat.objects.create(user=rival, iso_year=y, iso_week=w, xp=900)
    WeeklyStat.objects.create(user=user, iso_year=y, iso_week=w, xp=100)
    ensure_league_membership(rival)
    token = api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]
    for query in ("scope=league", "scope=global", "scope=global&period=all"):
        entries = api.get(f"/leaderboard?{query}", token=token).json()["entries"]
        by_name = {e["name"]: e for e in entries}
        assert by_name["Đối Thủ"]["avatar_frame"] == "frame_dragon"
        assert by_name["Đối Thủ"]["avatar_frame_colors"] == dragon.meta["colors"]
        assert by_name["Học Viên"]["avatar_frame"] is None
        assert by_name["Học Viên"]["avatar_frame_colors"] == []
