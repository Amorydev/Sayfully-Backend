"""Seed kịch bản đóng vai (C44) từ `apps.ai.scenarios_data`. Idempotent theo (level, order)."""

from django.core.management.base import BaseCommand

from apps.ai.models import RoleplayScenario
from apps.ai.scenarios_data import SCENARIOS
from apps.common.learning_goals import scenario_goals


def seed_roleplay_scenarios() -> int:
    for item in SCENARIOS:
        RoleplayScenario.objects.update_or_create(
            level=item["level"],
            order=item["order"],
            defaults={
                **{k: v for k, v in item.items() if k not in ("level", "order")},
                # Kịch bản không ghi mục tiêu thì suy từ bối cảnh, để gợi ý Gia sư AI luôn có dữ liệu.
                "learning_goals": item.get("learning_goals")
                or scenario_goals(item.get("scene", ""), item.get("topic", "")),
            },
        )
    return len(SCENARIOS)


class Command(BaseCommand):
    help = "Seed kịch bản đóng vai cho Gia sư AI."

    def handle(self, *args, **opts):
        n = seed_roleplay_scenarios()
        self.stdout.write(self.style.SUCCESS(f"Đã seed {n} kịch bản đóng vai."))
