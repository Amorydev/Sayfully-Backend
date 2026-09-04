"""G5 bundle: build_bundles command, build_level_bundle, manifest endpoint."""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.content.bundle import build_level_bundle
from apps.content.management.commands import build_bundles as bb
from apps.content.models import ContentBundle, Lesson, LessonStep, Level, Unit, Vocabulary

pytestmark = pytest.mark.django_db


@pytest.fixture
def token(api, user, password):
    return api.post("/auth/token", {"email": user.email, "password": password}).json()["access"]


@pytest.fixture
def a1_content():
    a1 = Level.objects.create(code="A1", name_vi="Sơ cấp", order=1, is_free=True)
    unit = Unit.objects.create(level=a1, order=1, code="a1-u1", title_vi="U", title_en="U",
                               reward={"coins": 150})
    lesson = Lesson.objects.create(unit=unit, order=1, code="a1-u1-l1", title_vi="B", title_en="L")
    v = Vocabulary.objects.create(headword="apple", pos="n", level=a1, meaning_vi="táo",
                                  ipa_uk="/uk/", ipa_us="/us/")
    LessonStep.objects.create(lesson=lesson, order=1, kind="vocab", vocabulary=v)
    LessonStep.objects.create(lesson=lesson, order=2, kind="quiz",
                              payload={"prompt_vi": "?", "options": ["a"], "correct_index": 0})
    return a1


# --------------------------------------------------------------- build_level_bundle
def test_build_level_bundle_structure(a1_content):
    b = build_level_bundle(a1_content)
    assert b["level"] == "A1"
    unit = b["units"][0]
    assert unit["reward"] == {"coins": 150}
    steps = unit["lessons"][0]["steps"]
    assert steps[0]["kind"] == "vocab" and steps[0]["vocab"]["headword"] == "apple"
    assert steps[0]["vocab"]["ipa_uk"] == "/uk/" and steps[0]["vocab"]["ipa_us"] == "/us/"
    assert steps[1]["kind"] == "quiz" and steps[1]["quiz"]["correct_index"] == 0


# --------------------------------------------------------------- build_bundles command
@pytest.fixture
def fake_upload(monkeypatch):
    calls = []
    monkeypatch.setattr(bb, "upload_bundle", lambda key, data: calls.append((key, data)) or key)
    return calls


def test_build_bundles_tao_row(a1_content, fake_upload):
    call_command("build_bundles", "--level", "A1", stdout=StringIO())
    cb = ContentBundle.objects.get(level=a1_content)
    assert cb.version == 1 and cb.size > 0 and len(cb.checksum) == 64
    assert cb.url.endswith("content/v1/a1.json")
    assert fake_upload[0][0] == "content/v1/a1.json"


def test_build_bundles_bump_version(a1_content, fake_upload):
    call_command("build_bundles", "--level", "A1", stdout=StringIO())
    call_command("build_bundles", "--level", "A1", stdout=StringIO())
    assert ContentBundle.objects.get(level=a1_content).version == 2


def test_build_bundles_dry_run(a1_content, fake_upload):
    call_command("build_bundles", "--level", "A1", "--dry-run", stdout=StringIO())
    assert ContentBundle.objects.count() == 0 and fake_upload == []


# --------------------------------------------------------------- manifest endpoint
def test_manifest_khong_token_401(api, a1_content):
    assert api.get("/content/manifest").status_code == 401


def test_manifest(api, token, a1_content, fake_upload):
    call_command("build_bundles", stdout=StringIO())
    body = api.get("/content/manifest", token=token).json()
    assert body["version"] == 1
    assert body["levels"][0]["code"] == "A1"
    assert len(body["levels"][0]["checksum"]) == 64
