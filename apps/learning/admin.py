from django.contrib import admin

from . import models as m


@admin.register(m.LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ("user", "lesson", "status", "stars", "xp_earned", "completed_at")
    list_filter = ("status",)
    search_fields = ("user__email", "lesson__code")
    raw_id_fields = ("user", "lesson")


@admin.register(m.SRSCard)
class SRSCardAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "vocabulary",
        "state",
        "due_at",
        "stability",
        "difficulty",
        "reps",
        "lapses",
    )
    list_filter = ("state",)
    search_fields = ("user__email", "vocabulary__headword")
    raw_id_fields = ("user", "vocabulary")


@admin.register(m.SRSReviewLog)
class SRSReviewLogAdmin(admin.ModelAdmin):
    list_display = ("user", "vocabulary", "rating", "reviewed_at")
    raw_id_fields = ("user", "vocabulary")


@admin.register(m.NotebookEntry)
class NotebookEntryAdmin(admin.ModelAdmin):
    list_display = ("user", "vocabulary", "custom_word", "created_at")
    raw_id_fields = ("user", "vocabulary")


@admin.register(m.DailyActivity)
class DailyActivityAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "xp", "lessons_completed", "words_reviewed", "minutes")
    list_filter = ("date",)
    raw_id_fields = ("user",)


@admin.register(m.WeeklyStat)
class WeeklyStatAdmin(admin.ModelAdmin):
    list_display = ("user", "iso_year", "iso_week", "xp", "days_active")
    raw_id_fields = ("user",)


@admin.register(m.PlacementQuestion)
class PlacementQuestionAdmin(admin.ModelAdmin):
    list_display = ("order", "skill", "level", "prompt_en", "is_active")
    list_filter = ("skill", "level")


@admin.register(m.PlacementAttempt)
class PlacementAttemptAdmin(admin.ModelAdmin):
    list_display = ("user", "suggested_level", "suggested_unit", "created_at")
    raw_id_fields = ("user",)
