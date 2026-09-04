from django.db import models

from apps.accounts.models import User
from apps.common.models import CEFR


class RoleplayScenario(models.Model):
    level = models.CharField(max_length=2, choices=CEFR.choices)
    topic = models.CharField(max_length=48)
    title_vi = models.CharField(max_length=128)
    description_vi = models.CharField(max_length=255)
    goals = models.JSONField(default=list)  # ["Chào & gọi món","Chọn size",...]
    system_prompt = models.TextField()
    thumbnail_path = models.CharField(max_length=255, blank=True)
    is_premium = models.BooleanField(default=True)

    def __str__(self) -> str:
        return str(self.title_vi)


class AIConversation(models.Model):
    class Kind(models.TextChoices):
        TUTOR = "tutor", "Gia sư"
        ROLEPLAY = "roleplay", "Đóng vai"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ai_conversations")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    scenario = models.ForeignKey(RoleplayScenario, null=True, blank=True, on_delete=models.SET_NULL)
    goals_state = models.JSONField(default=list, blank=True)  # [true,false,...]
    result = models.JSONField(default=dict, blank=True)  # {"goals":4,"pronunciation":88}
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "-created_at"], name="conv_user_recent_idx")]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.kind}"


class AIMessage(models.Model):
    conversation = models.ForeignKey(
        AIConversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10)  # user | assistant | system
    content = models.TextField()
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["conversation", "created_at"], name="msg_conv_idx")]

    def __str__(self) -> str:
        return f"{self.role}: {self.content[:40]}"


class AIQuota(models.Model):
    """Chặn lạm dụng + kiểm soát chi phí LLM."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ai_quotas")
    date = models.DateField()
    messages_used = models.PositiveSmallIntegerField(default=0)
    tokens_used = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "date"], name="uniq_ai_quota")]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.date}"
