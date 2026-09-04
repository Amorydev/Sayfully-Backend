from django.contrib import admin

from . import models as m


@admin.register(m.BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "is_published", "published_at", "reading_minutes")
    list_filter = ("is_published", "category")
    search_fields = ("title", "slug", "excerpt")
    prepopulated_fields = {"slug": ("title",)}
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "title",
                    "slug",
                    "category",
                    "excerpt",
                    "content",
                    "cover_path",
                    "reading_minutes",
                    "author",
                )
            },
        ),
        ("SEO", {"fields": ("meta_title", "meta_description", "og_image_path")}),
        ("Xuất bản", {"fields": ("is_published", "published_at")}),
    )
