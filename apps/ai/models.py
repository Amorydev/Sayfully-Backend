from django.db import models

from apps.accounts.models import User
from apps.common.models import CEFR


class RoleplayScenario(models.Model):
    level = models.CharField(max_length=2, choices=CEFR.choices)
    order = models.PositiveSmallIntegerField(default=0)
    topic = models.CharField(max_length=48)
    scene = models.CharField(
        max_length=32, blank=True
    )  # cafe | airport | hotel | directions | interview | doctor
    title_vi = models.CharField(max_length=128)
    description_vi = models.CharField(max_length=255)
    ai_role_vi = models.CharField(max_length=64, blank=True)  # "Nhân viên quán"
    user_role_vi = models.CharField(max_length=64, blank=True)  # "Khách hàng"
    goals = models.JSONField(default=list)  # ["Chào & gọi món","Chọn size",...]
    goal_hints = models.JSONField(default=list, blank=True)  # câu mẫu tiếng Anh tương ứng từng goal
    tip_vi = models.CharField(max_length=255, blank=True)
    system_prompt = models.TextField()
    thumbnail_path = models.CharField(max_length=255, blank=True)
    duration_min = models.PositiveSmallIntegerField(default=5)
    xp_reward = models.PositiveSmallIntegerField(default=30)
    coin_reward = models.PositiveSmallIntegerField(default=15)
    is_premium = models.BooleanField(default=True)

    class Meta:
        ordering = ["level", "order", "id"]

    def __str__(self) -> str:
        return str(self.title_vi)


class AIConversation(models.Model):
    class Kind(models.TextChoices):
        TUTOR = "tutor", "Gia sư"
        ROLEPLAY = "roleplay", "Đóng vai"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ai_conversations")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    scenario = models.ForeignKey(RoleplayScenario, null=True, blank=True, on_delete=models.SET_NULL)
    topic = models.CharField(max_length=48, blank=True)
    title_vi = models.CharField(max_length=128, blank=True)
    use_notebook = models.BooleanField(default=True)
    turn_count = models.PositiveSmallIntegerField(default=0)  # số lượt người học đã nói
    goals_state = models.JSONField(default=list, blank=True)  # [true,false,...]
    goal_evidence = models.JSONField(default=list, blank=True)  # câu người học đạt mục tiêu
    result = models.JSONField(default=dict, blank=True)  # tổng kết sau /end
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
    meta = models.JSONField(default=dict, blank=True)  # correction/vocab/reply_vi/suggested_replies
    client_msg_id = models.CharField(max_length=64, blank=True)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
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
