"""Django Admin cho nội dung — nơi nhập liệu hằng ngày, có inline & cảnh báo thiếu audio/IPA."""

from django.contrib import admin
from django.utils.html import format_html

from . import models as m


def _audio(path: str) -> str:
    return (
        format_html('<span style="color:#0E9F6E">●</span>')
        if path
        else format_html('<span style="color:#DC2626" title="thiếu audio">●</span>')
    )


@admin.register(m.Level)
class LevelAdmin(admin.ModelAdmin):
    list_display = ("code", "name_vi", "order", "word_target", "is_free")
    ordering = ("order",)


@admin.register(m.Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("code", "name_vi", "name_en", "order")
    search_fields = ("code", "name_vi", "name_en")


class LessonInline(admin.TabularInline):
    model = m.Lesson
    extra = 0
    fields = ("order", "code", "title_vi", "title_en", "est_minutes", "xp_reward")


@admin.register(m.Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("level", "order", "title_vi", "title_en")
    list_filter = ("level",)
    search_fields = ("title_vi", "title_en", "code")
    inlines = [LessonInline]


class LessonStepInline(admin.TabularInline):
    model = m.LessonStep
    extra = 0
    autocomplete_fields = ("vocabulary", "grammar_point", "dialogue")
    fields = ("order", "kind", "vocabulary", "grammar_point", "dialogue", "payload")


@admin.register(m.Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("code", "unit", "order", "title_vi", "est_minutes", "xp_reward", "step_count")
    list_filter = ("unit__level",)
    search_fields = ("code", "title_vi", "title_en")
    inlines = [LessonStepInline]

    @admin.display(description="Bước")
    def step_count(self, obj):
        return obj.steps.count()


class ExampleInline(admin.TabularInline):
    model = m.VocabularyExample
    extra = 0


class CollocationInline(admin.TabularInline):
    model = m.Collocation
    extra = 0


class MissingAudioFilter(admin.SimpleListFilter):
    title = "audio"
    parameter_name = "audio"

    def lookups(self, request, model_admin):
        return [("missing", "Thiếu audio"), ("ok", "Đủ audio")]

    def queryset(self, request, qs):
        if self.value() == "missing":
            return qs.filter(audio_us_path="") | qs.filter(audio_uk_path="")
        if self.value() == "ok":
            return qs.exclude(audio_us_path="").exclude(audio_uk_path="")
        return qs


class MissingIPAFilter(admin.SimpleListFilter):
    title = "IPA"
    parameter_name = "ipa"

    def lookups(self, request, model_admin):
        return [("missing", "Thiếu IPA"), ("ok", "Đủ IPA")]

    def queryset(self, request, qs):
        if self.value() == "missing":
            return qs.filter(ipa_us="") | qs.filter(ipa_uk="")
        if self.value() == "ok":
            return qs.exclude(ipa_us="").exclude(ipa_uk="")
        return qs


@admin.register(m.Vocabulary)
class VocabularyAdmin(admin.ModelAdmin):
    list_display = (
        "headword",
        "pos",
        "level",
        "meaning_vi",
        "ipa_us",
        "audio_us",
        "audio_uk",
        "frequency_rank",
    )
    list_filter = ("level", "pos", MissingAudioFilter, MissingIPAFilter, "topics")
    search_fields = ("headword", "meaning_vi", "ipa_us")
    filter_horizontal = ("topics", "word_family")
    inlines = [ExampleInline, CollocationInline]
    list_per_page = 50

    @admin.display(description="US")
    def audio_us(self, obj):
        return _audio(obj.audio_us_path)

    @admin.display(description="UK")
    def audio_uk(self, obj):
        return _audio(obj.audio_uk_path)


class GrammarExampleInline(admin.TabularInline):
    model = m.GrammarExample
    extra = 0


@admin.register(m.GrammarPoint)
class GrammarPointAdmin(admin.ModelAdmin):
    list_display = ("level", "order", "title_vi", "category", "formula")
    list_filter = ("level", "category")
    search_fields = ("title_vi", "title_en", "formula")
    inlines = [GrammarExampleInline]


class DialogueLineInline(admin.TabularInline):
    model = m.DialogueLine
    extra = 0


@admin.register(m.Dialogue)
class DialogueAdmin(admin.ModelAdmin):
    list_display = ("title_en", "title_vi", "lesson")
    search_fields = ("title_en", "title_vi")
    inlines = [DialogueLineInline]


class ReadingSentenceInline(admin.TabularInline):
    model = m.ReadingSentence
    extra = 0


class ReadingQuestionInline(admin.TabularInline):
    model = m.ReadingQuestion
    extra = 0


@admin.register(m.Reading)
class ReadingAdmin(admin.ModelAdmin):
    list_display = ("level", "order", "title_en", "title_vi", "topic", "est_minutes")
    list_filter = ("level", "topic")
    search_fields = ("title_en", "title_vi")
    filter_horizontal = ("keywords",)
    inlines = [ReadingSentenceInline, ReadingQuestionInline]


class StorySceneInline(admin.TabularInline):
    model = m.StoryScene
    extra = 0


class StoryQuestionInline(admin.TabularInline):
    model = m.StoryQuestion
    extra = 0


@admin.register(m.Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = ("level", "order", "title_en", "title_vi", "genre")
    list_filter = ("level", "genre")
    search_fields = ("title_en", "title_vi")
    inlines = [StorySceneInline, StoryQuestionInline]


class StorySentenceInline(admin.TabularInline):
    model = m.StorySentence
    extra = 0


@admin.register(m.StoryScene)
class StorySceneAdmin(admin.ModelAdmin):
    list_display = ("story", "order")
    inlines = [StorySentenceInline]


class VideoSubtitleInline(admin.TabularInline):
    model = m.VideoSubtitle
    extra = 0


@admin.register(m.Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("title_vi", "level", "category", "youtube_id", "duration_sec", "is_free")
    list_filter = ("level", "category", "is_free")
    search_fields = ("title_vi", "title_en", "youtube_id")
    inlines = [VideoSubtitleInline]


@admin.register(m.WordRoot)
class WordRootAdmin(admin.ModelAdmin):
    list_display = ("kind", "text", "meaning_vi", "group_vi")
    list_filter = ("kind", "group_vi")
    search_fields = ("text", "meaning_vi")
    filter_horizontal = ("examples",)


@admin.register(m.PhrasalVerb)
class PhrasalVerbAdmin(admin.ModelAdmin):
    list_display = ("text", "verb_group", "meaning_vi", "level")
    list_filter = ("verb_group", "level")
    search_fields = ("text", "meaning_vi")


@admin.register(m.IPASound)
class IPASoundAdmin(admin.ModelAdmin):
    list_display = ("symbol", "kind", "description_vi", "order")
    list_filter = ("kind",)
    ordering = ("order",)
