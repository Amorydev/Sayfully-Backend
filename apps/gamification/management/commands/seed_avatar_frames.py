from django.core.management.base import BaseCommand

from apps.gamification.avatar_frames import AVATAR_FRAMES, seed_avatar_frames


class Command(BaseCommand):
    help = "Sync 12 avatar frames without resetting prices, ownership or availability."

    def handle(self, *args, **options):
        created = seed_avatar_frames()
        self.stdout.write(self.style.SUCCESS(f"Synced {len(AVATAR_FRAMES)} avatar frames ({created} new)."))
