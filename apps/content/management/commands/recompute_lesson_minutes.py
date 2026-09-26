from django.core.management.base import BaseCommand

from apps.content.lesson_minutes import recompute_lesson_minutes


class Command(BaseCommand):
    help = "Tính lại est_minutes của mọi bài học theo số bước và độ dài hội thoại."

    def handle(self, *args, **opts):
        changed = recompute_lesson_minutes()
        self.stdout.write(self.style.SUCCESS(f"Đã cập nhật est_minutes cho {changed} bài."))
