"""Model trừu tượng và choices dùng chung toàn hệ thống."""

import uuid

from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDModel(models.Model):
    """Dùng cho bảng gắn với user — id khó đoán, an toàn khi lộ ra API."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class CEFR(models.TextChoices):
    A1 = "A1", "A1 — Mới bắt đầu"
    A2 = "A2", "A2 — Sơ cấp"
    B1 = "B1", "B1 — Trung cấp"
    B2 = "B2", "B2 — Trung cao"
    C1 = "C1", "C1 — Cao cấp"
    C2 = "C2", "C2 — Thành thạo"


class Accent(models.TextChoices):
    UK = "UK", "Anh-Anh"
    US = "US", "Anh-Mỹ"
