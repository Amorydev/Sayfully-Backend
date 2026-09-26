"""Xoá sạch DB rồi nạp lại nội dung từ Data/REVIEW_skills.xlsx (nguồn sự thật duy nhất).

  python manage.py reset_content --yes                       # flush → import_review_skills → seed_catalog/scenarios/match_pairs → tài khoản ban đầu → admin + demo
  python manage.py reset_content --yes --xlsx /path/file.xlsx

Giữ lại 2 tài khoản `admin@sayfully.com` và `demo@sayfully.app` (cùng mật khẩu cũ — chép hash), mọi
user/tiến độ khác mất. Không có `--yes` thì chỉ in ra sẽ làm gì.
"""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.services import ensure_profile

KEEP = ("admin@sayfully.com", "demo@sayfully.app")


class Command(BaseCommand):
    help = "Xoá toàn bộ DB và nạp lại từ REVIEW_skills.xlsx; giữ admin + demo."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Thực sự xoá (không hỏi lại).")
        parser.add_argument(
            "--xlsx", default="", help="Đường dẫn workbook; mặc định ../Data/REVIEW_skills.xlsx"
        )

    def handle(self, *args, **opts):
        user_model = get_user_model()
        kept = [
            {
                "email": u.email,
                "password": u.password,
                "full_name": u.full_name,
                "is_staff": u.is_staff,
                "is_superuser": u.is_superuser,
                "cefr_level": ensure_profile(u).cefr_level,
                "accent": ensure_profile(u).accent,
            }
            for u in user_model.objects.filter(email__in=KEEP)
        ]
        total = user_model.objects.count()
        if not opts["yes"]:
            raise CommandError(
                f"Sẽ xoá {total} user và toàn bộ dữ liệu, giữ {len(kept)} tài khoản {', '.join(k['email'] for k in kept)}. "
                "Chạy lại với --yes để thực hiện."
            )
        self.stdout.write(f"Xoá toàn bộ DB ({total} user)…")
        # Một transaction: workbook lỗi giữa chừng thì DB (kể cả user) vẫn nguyên.
        with transaction.atomic():
            call_command("flush", interactive=False, verbosity=0)
            import_opts = {"xlsx": opts["xlsx"]} if opts["xlsx"] else {}
            call_command("import_review_skills", **import_opts)
            call_command("seed_catalog")  # nhiệm vụ · huy hiệu · cửa hàng · game · gói · mã quà
            call_command("seed_scenarios")  # kịch bản đóng vai Gia sư AI
            call_command("seed_match_pairs")  # chặng Ghép cặp
            # tài khoản ban đầu nạp lại sau seed_catalog để có huy hiệu + khung avatar
            call_command("import_review_skills", only="accounts", **import_opts)
            for k in kept:
                u = user_model(
                    email=k["email"],
                    full_name=k["full_name"],
                    is_staff=k["is_staff"],
                    is_superuser=k["is_superuser"],
                )
                u.password = k["password"]  # hash cũ, mật khẩu không đổi
                u.save()
                profile = ensure_profile(u)
                profile.cefr_level = k["cefr_level"]
                profile.accent = k["accent"]
                profile.onboarding_completed = True
                profile.save(update_fields=["cefr_level", "accent", "onboarding_completed"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Xong. Giữ lại {len(kept)} tài khoản: {', '.join(k['email'] for k in kept)}"
            )
        )
