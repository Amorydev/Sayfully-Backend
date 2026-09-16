"""Audio hai giọng (US/UK) cho mọi bảng câu: đổi `audio_path` → `audio_us_path`, thêm `audio_uk_path`.
JSON (PhrasalVerb.examples, LessonStep.payload) đổi khoá tương ứng."""

from django.db import migrations, models

SENTENCE_MODELS = [
    "vocabularyexample",
    "grammarexample",
    "dialogueline",
    "readingsentence",
    "storysentence",
    "shadowingsentence",
    "listeningitem",
]


def _rename_key(item: dict) -> dict:
    if isinstance(item, dict) and "audio_path" in item:
        item = dict(item)
        item["audio_us_path"] = item.pop("audio_path") or ""
        item.setdefault("audio_uk_path", "")
    return item


def forwards(apps, schema_editor):
    PhrasalVerb = apps.get_model("content", "PhrasalVerb")
    for pv in PhrasalVerb.objects.all():
        if any(isinstance(x, dict) and "audio_path" in x for x in pv.examples or []):
            pv.examples = [_rename_key(x) for x in pv.examples]
            pv.save(update_fields=["examples"])

    LessonStep = apps.get_model("content", "LessonStep")
    for step in LessonStep.objects.exclude(payload={}):
        p = dict(step.payload or {})
        changed = False
        if isinstance(p.get("preview"), list):
            p["preview"] = [_rename_key(x) for x in p["preview"]]
            changed = True
        if "audio_path" in p:
            p = _rename_key(p)
            changed = True
        if changed:
            step.payload = p
            step.save(update_fields=["payload"])


def backwards(apps, schema_editor):
    PhrasalVerb = apps.get_model("content", "PhrasalVerb")
    for pv in PhrasalVerb.objects.all():
        out = []
        for x in pv.examples or []:
            if isinstance(x, dict) and "audio_us_path" in x:
                x = dict(x)
                x["audio_path"] = x.pop("audio_us_path")
                x.pop("audio_uk_path", None)
            out.append(x)
        pv.examples = out
        pv.save(update_fields=["examples"])


class Migration(migrations.Migration):
    dependencies = [("content", "0023_video_featured")]

    operations = [
        *[
            migrations.RenameField(model_name=m, old_name="audio_path", new_name="audio_us_path")
            for m in SENTENCE_MODELS
        ],
        *[
            migrations.AddField(
                model_name=m,
                name="audio_uk_path",
                field=models.CharField(blank=True, max_length=255),
            )
            for m in SENTENCE_MODELS
        ],
        migrations.RunPython(forwards, backwards),
    ]
