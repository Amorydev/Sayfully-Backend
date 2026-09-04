"""G5 — Đóng gói nội dung thành JSON tĩnh → upload R2 → cập nhật manifest (ContentBundle).

Mỗi cấp một file `content/v{version}/{code}.json`. Version mới = max hiện có + 1 (các cấp
build trong lần này dùng chung version mới; cấp không build giữ nguyên — app so checksum
để tải lại phần đổi). `--dry-run` không upload/không ghi DB.

Uploader là hàm cấp module (`upload_bundle`) — test thay bằng hàm giả; production dùng R2.
"""

import hashlib
import json

from django.core.management.base import BaseCommand
from django.db.models import Max

from apps.content.bundle import build_level_bundle
from apps.content.models import ContentBundle, Level


def upload_bundle(key: str, data: bytes) -> str:
    import boto3  # noqa: PLC0415
    from django.conf import settings

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )
    client.put_object(
        Bucket=settings.R2_BUCKET, Key=key, Body=data, ContentType="application/json"
    )
    return key


class Command(BaseCommand):
    help = "Đóng gói nội dung theo cấp → R2 + cập nhật manifest."

    def add_arguments(self, parser):
        parser.add_argument("--level", help="Chỉ đóng gói một cấp, ví dụ A1.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        from django.conf import settings

        dry = opts["dry_run"]
        levels = Level.objects.all()
        if opts["level"]:
            levels = levels.filter(code=opts["level"].upper())
        if not levels:
            self.stderr.write("Không có cấp nào khớp.")
            return

        version = (ContentBundle.objects.aggregate(m=Max("version"))["m"] or 0) + 1
        base = settings.R2_PUBLIC_BASE.rstrip("/")
        for level in levels:
            data = json.dumps(build_level_bundle(level), ensure_ascii=False).encode("utf-8")
            checksum = hashlib.sha256(data).hexdigest()
            key = f"content/v{version}/{level.code.lower()}.json"
            if not dry:
                upload_bundle(key, data)
                ContentBundle.objects.update_or_create(
                    level=level,
                    defaults={
                        "version": version,
                        "url": f"{base}/{key}",
                        "checksum": checksum,
                        "size": len(data),
                    },
                )
            self.stdout.write(f"{level.code}: {len(data)} bytes · {checksum[:12]}…")

        tag = "[DRY-RUN] " if dry else ""
        self.stdout.write(self.style.SUCCESS(f"{tag}Đóng gói {len(levels)} cấp, version {version}."))
