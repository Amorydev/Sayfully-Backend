"""Bài blog phục vụ SEO — Next.js render tĩnh qua /public/posts (G9)."""

from django.db import models

from apps.accounts.models import User
from apps.common.models import TimeStampedModel


class BlogPost(TimeStampedModel):
    slug = models.SlugField(max_length=160, unique=True)
    title = models.CharField(max_length=200)
    excerpt = models.CharField(max_length=320, blank=True)
    content = models.TextField()  # Markdown
    category = models.CharField(max_length=48, blank=True)
    cover_path = models.CharField(max_length=255, blank=True)
    reading_minutes = models.PositiveSmallIntegerField(default=5)
    author = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)

    # SEO
    meta_title = models.CharField(max_length=70, blank=True)
    meta_description = models.CharField(max_length=160, blank=True)
    og_image_path = models.CharField(max_length=255, blank=True)

    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "blog_posts"
        indexes = [
            models.Index(fields=["is_published", "-published_at"], name="post_pub_idx"),
            models.Index(fields=["category"], name="post_category_idx"),
        ]

    def __str__(self) -> str:
        return self.title
