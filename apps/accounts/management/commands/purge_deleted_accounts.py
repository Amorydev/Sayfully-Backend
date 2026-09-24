from django.core.management.base import BaseCommand

from apps.accounts.tasks import purge_deleted_accounts


class Command(BaseCommand):
    help = "Xoá cứng tài khoản đã yêu cầu xoá quá 30 ngày (worker cũng chạy hằng ngày)."

    def handle(self, *args, **options):
        count = purge_deleted_accounts()
        self.stdout.write(f"Đã xoá cứng {count} tài khoản")
