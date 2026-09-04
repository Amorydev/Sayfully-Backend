from django.contrib import admin

from . import models as m


class ExamQuestionInline(admin.TabularInline):
    model = m.ExamQuestion
    extra = 0
    fields = ("order", "qtype", "prompt_en", "audio_path", "options", "answer", "points")


@admin.register(m.ExamSection)
class ExamSectionAdmin(admin.ModelAdmin):
    list_display = ("exam", "order", "kind", "title")
    inlines = [ExamQuestionInline]


class ExamSectionInline(admin.TabularInline):
    model = m.ExamSection
    extra = 0
    show_change_link = True


@admin.register(m.Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "exam_type",
        "band_group",
        "difficulty",
        "duration_min",
        "total_questions",
        "is_free",
        "is_active",
    )
    list_filter = ("exam_type", "band_group", "difficulty", "is_free")
    search_fields = ("code", "title_vi")
    inlines = [ExamSectionInline]


@admin.register(m.ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = ("user", "exam", "score", "band_result", "is_passed", "submitted_at")
    list_filter = ("is_passed", "exam__exam_type")
    raw_id_fields = ("user",)


admin.site.register(m.ExamAnswer)
