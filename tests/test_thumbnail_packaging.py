import json
import re
from pathlib import Path

import pytest

from modules.project import thumbnail_packaging
from modules.project.thumbnail_packaging import (
    FFmpegThumbnailComposer,
    ThumbnailConcept,
    ThumbnailConceptDraft,
    ThumbnailPackagingEngine,
)


def _concepts():
    return ThumbnailConceptDraft(
        concepts=[
            ThumbnailConcept(
                concept_id="ignored-a",
                visual_concept="A pirate squints as a bright sun reveals one covered eye.",
                main_character_or_object="A surprised cartoon pirate with an eye patch",
                situation="The pirate is caught between a dark ship cabin and bright sunlight.",
                text="PATCH WHY?",
                composition="Large pirate on the left with the eye patch clearly visible.",
                curiosity_reason="The patch appears connected to a surprising practical trick.",
                title_relationship="Raises the reason behind the patch without repeating the title.",
                artwork_prompt="Draw a simple cartoon pirate with an eye patch.",
            ),
            ThumbnailConcept(
                concept_id="ignored-b",
                visual_concept="One pirate eye sees darkness while the other faces sunlight.",
                main_character_or_object="A pirate face split between dark and bright spaces",
                situation="A clear contrast shows two different light conditions.",
                text="TWO EYES?",
                composition="A large close-up face with a simple dark-light division.",
                curiosity_reason="The contrast makes viewers wonder why the eyes differ.",
                title_relationship="Adds a visual question rather than restating the final title.",
                artwork_prompt="Draw a face split between a dark room and daylight.",
            ),
            ThumbnailConcept(
                concept_id="ignored-c",
                visual_concept="A tiny stickman pirate dramatically swaps an eye patch.",
                main_character_or_object="A doodle pirate holding an eye patch",
                situation="The pirate reacts to a sudden burst of sunlight.",
                text="DARK TO LIGHT",
                composition="One large pirate figure and an oversized patch against yellow.",
                curiosity_reason="The sudden light change suggests a practical secret.",
                title_relationship="Hints at adaptation without copying the final title.",
                artwork_prompt="Draw a doodle pirate reacting to bright sunlight.",
            ),
        ]
    )


class FakeConceptGenerator:
    def __init__(self, draft=None):
        self.draft = draft or _concepts()
        self.contexts = []

    def generate(self, context):
        self.contexts.append(context)
        return self.draft


class FakeArtworkGenerator:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return b"mock-generated-png"


class FakeComposer:
    def __init__(self):
        self.calls = []

    def compose(self, artwork_path: Path, output_path: Path, text: str):
        self.calls.append((artwork_path.read_bytes(), text))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"mock-composed-thumbnail")
        return output_path


def _project(tmp_path):
    project = tmp_path / "20261005_001_project"
    (project / "script").mkdir(parents=True)
    (project / "research").mkdir()
    (project / "video").mkdir()
    (project / "topic_selection.json").write_text(
        json.dumps({"topic": "Why Do Pirates Wear Eye Patches?"}),
        encoding="utf-8",
    )
    (project / "metadata_packaging.json").write_text(
        json.dumps(
            {
                "status": "COMPLETE",
                "selected_title": "Why Pirates Wore Eye Patches for a Surprising Reason",
                "description": "The real story behind an iconic pirate accessory.",
            }
        ),
        encoding="utf-8",
    )
    (project / "script" / "script.json").write_text(
        json.dumps(
            {
                "sections": [
                    {"title": "Opening", "narration": "Pirates moved between dark decks and sunlight."}
                ]
            }
        ),
        encoding="utf-8",
    )
    (project / "research" / "research.json").write_text(
        json.dumps({"key_facts": ["An eye could adapt to darkness."]}),
        encoding="utf-8",
    )
    (project / "video" / "ritzz_test.mp4").write_bytes(b"mock-video")
    return project


def _engine(concepts=None, artwork=None, composer=None, *, dimensions=None):
    return ThumbnailPackagingEngine(
        concept_generator=concepts or FakeConceptGenerator(),
        artwork_generator=artwork or FakeArtworkGenerator(),
        composer=composer or FakeComposer(),
        image_probe=lambda _path: dimensions or {"width": 1280, "height": 720},
        clock=lambda: "2026-10-05T00:00:00+00:00",
    )


def test_concepts_are_accurate_short_and_cached_without_regeneration(tmp_path):
    project = _project(tmp_path)
    generator = FakeConceptGenerator()
    engine = _engine(concepts=generator)

    first = engine.create_concepts(
        project,
        production_id="production-1",
        project_id="20261005_001",
    )

    class MustNotGenerate:
        def generate(self, _context):
            pytest.fail("Saved thumbnail concepts must be reused.")

    second = ThumbnailPackagingEngine(
        concept_generator=MustNotGenerate(),
        clock=lambda: "2026-10-05T00:00:00+00:00",
    ).create_concepts(
        project,
        production_id="production-1",
        project_id="20261005_001",
    )

    assert len(first["concepts"]) == 3
    assert [item["concept_id"] for item in first["concepts"]] == [
        "concept-1",
        "concept-2",
        "concept-3",
    ]
    assert all(item["text"].isupper() for item in first["concepts"])
    assert len(generator.contexts) == 1
    assert "final_script" in generator.contexts[0]
    assert "final_research" in generator.contexts[0]
    assert second == first


def test_selected_concept_generates_one_clean_artwork_and_composites_exact_text(tmp_path):
    project = _project(tmp_path)
    concept_generator = FakeConceptGenerator()
    artwork_generator = FakeArtworkGenerator()
    composer = FakeComposer()
    engine = _engine(concept_generator, artwork_generator, composer)
    engine.create_concepts(
        project,
        production_id="production-1",
        project_id="20261005_001",
    )

    artifact = engine.render_selected(
        project,
        production_id="production-1",
        project_id="20261005_001",
        concept_id="concept-2",
    )

    assert artifact["status"] == "COMPLETE"
    assert artifact["selected_concept_id"] == "concept-2"
    assert len(artwork_generator.prompts) == 1
    assert "no text, letters, words, numbers" in artwork_generator.prompts[0].lower()
    assert "RITZZ style" in artwork_generator.prompts[0]
    assert "TWO EYES?" not in artwork_generator.prompts[0]
    assert composer.calls == [(b"mock-generated-png", "TWO EYES?")]
    assert artifact["rendered_text"] == "TWO EYES?"
    assert artifact["qa"]["thumbnail_exists"] == "PASS"
    assert artifact["qa"]["image_readable"] == "PASS"
    assert artifact["qa"]["dimensions"] == "PASS"
    assert artifact["qa"]["aspect_ratio"] == "PASS"
    assert artifact["qa"]["text_word_count"] == 2
    assert artifact["qa"]["safe_margins"] == "PASS"
    assert artifact["qa"]["visual_text_review"] == "REQUIRED"
    assert artifact["qa"]["artwork_has_no_editorial_text"] == "REVIEW"
    assert artifact["qa"]["overall_status"] == "REVIEW"
    assert artifact["human_review_status"] == "REVIEW"
    assert (project / "video" / "thumbnail.jpg").is_file()
    assert (project / "video" / "thumbnail_artwork.png").is_file()


def test_completed_thumbnail_is_reused_without_image_or_ffmpeg_calls(tmp_path):
    project = _project(tmp_path)
    artwork = FakeArtworkGenerator()
    composer = FakeComposer()
    engine = _engine(artwork=artwork, composer=composer)
    engine.create_concepts(
        project,
        production_id="production-1",
        project_id="20261005_001",
    )
    original = engine.render_selected(
        project,
        production_id="production-1",
        project_id="20261005_001",
        concept_id="concept-1",
    )

    class MustNotGenerate:
        def generate(self, _prompt):
            pytest.fail("A completed thumbnail must not call image generation.")

    class MustNotCompose:
        def compose(self, *_args):
            pytest.fail("A completed thumbnail must not be recomposed.")

    reused = ThumbnailPackagingEngine(
        artwork_generator=MustNotGenerate(),
        composer=MustNotCompose(),
        image_probe=lambda _path: {"width": 1280, "height": 720},
    ).render_selected(
        project,
        production_id="production-1",
        project_id="20261005_001",
        concept_id="concept-3",
    )

    assert reused == original
    assert len(artwork.prompts) == 1
    assert len(composer.calls) == 1


def test_failed_thumbnail_can_retry_using_saved_concepts_only(tmp_path):
    project = _project(tmp_path)
    concept_generator = FakeConceptGenerator()
    artwork_generator = FakeArtworkGenerator()

    class FailingComposer:
        def compose(self, *_args):
            raise RuntimeError("ffmpeg failed")

    first_engine = _engine(
        concepts=concept_generator,
        artwork=artwork_generator,
        composer=FailingComposer(),
    )
    first_engine.create_concepts(
        project,
        production_id="production-1",
        project_id="20261005_001",
    )
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        first_engine.render_selected(
            project,
            production_id="production-1",
            project_id="20261005_001",
            concept_id="concept-1",
        )

    retry_composer = FakeComposer()
    retried = _engine(
        concepts=concept_generator,
        artwork=artwork_generator,
        composer=retry_composer,
    ).render_selected(
        project,
        production_id="production-1",
        project_id="20261005_001",
        concept_id="concept-1",
    )

    assert retried["status"] == "COMPLETE"
    assert len(concept_generator.contexts) == 1
    assert len(artwork_generator.prompts) == 1
    assert len(retry_composer.calls) == 1


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"text": "WHY PIRATES WEAR EYE PATCHES"}, "at most 24 characters"),
        ({"text": "WHY WHY?"}, "duplicate words"),
        ({"text": "TODO NOW"}, "placeholder"),
        ({"text": "WHY PIRATES?"}, "repeat the final title"),
    ],
)
def test_invalid_thumbnail_hook_is_rejected(tmp_path, updates, message):
    project = _project(tmp_path)
    if message == "repeat the final title":
        metadata_path = project / "metadata_packaging.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["selected_title"] = "WHY PIRATES?"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    draft = _concepts()
    first = draft.concepts[0].model_copy(update=updates)
    draft.concepts[0] = first
    engine = _engine(concepts=FakeConceptGenerator(draft))

    with pytest.raises(ValueError, match=message):
        engine.create_concepts(
            project,
            production_id="production-1",
            project_id="20261005_001",
        )


def test_thumbnail_qa_rejects_wrong_size_and_records_failed_status(tmp_path):
    project = _project(tmp_path)
    engine = _engine(dimensions={"width": 640, "height": 360})
    engine.create_concepts(
        project,
        production_id="production-1",
        project_id="20261005_001",
    )

    with pytest.raises(ValueError, match="1280x720"):
        engine.render_selected(
            project,
            production_id="production-1",
            project_id="20261005_001",
            concept_id="concept-1",
        )

    saved = json.loads((project / "thumbnail_packaging.json").read_text())
    assert saved["status"] == "FAILED"


def test_ffmpeg_composer_receives_exact_approved_text_and_renders_jpeg(
    tmp_path,
    monkeypatch,
):
    artwork = tmp_path / "artwork.png"
    artwork.write_bytes(b"generated-art")
    font = tmp_path / "font.ttf"
    font.write_bytes(b"test-font")
    output = tmp_path / "thumbnail.jpg"
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        filter_text = command[command.index("-vf") + 1]
        text_file = Path(re.search(r"textfile='([^']+)'", filter_text).group(1))
        captured["rendered_text"] = text_file.read_text(encoding="utf-8")
        output_path = Path(command[-1])
        output_path.write_bytes(b"composited-jpeg")

        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr(thumbnail_packaging, "_escape_filter_path", str)
    monkeypatch.setattr(thumbnail_packaging.subprocess, "run", fake_run)
    composer = FFmpegThumbnailComposer(ffmpeg_path="ffmpeg", font_path=font)

    result = composer.compose(artwork, output, "TWO EYES?")

    filter_text = captured["command"][captured["command"].index("-vf") + 1]
    assert "drawtext=" in filter_text
    assert "fontcolor=yellow" in filter_text
    assert "borderw=6:bordercolor=black" in filter_text
    assert captured["rendered_text"] == "TWO EYES?"
    assert result == output
    assert output.read_bytes() == b"composited-jpeg"


def test_thumbnail_workflow_stage_is_after_metadata_and_before_final_approval():
    workflow = Path(".github/workflows/ritzz-pipeline.yml").read_text(
        encoding="utf-8"
    )
    metadata = workflow.index("  metadata-packaging:")
    thumbnail = workflow.index("  thumbnail-packaging:")
    approval = workflow.index("  packaging-approval:")
    private_upload = workflow.index("  private-upload:")
    thumbnail_job = workflow[thumbnail:approval]

    assert metadata < thumbnail < approval < private_upload
    assert "needs: [metadata-packaging, restore-production]" in thumbnail_job
    assert "needs: [metadata-packaging, thumbnail-packaging, restore-production]" in (
        workflow[approval:private_upload]
    )
    assert "RITZZ_THUMBNAIL_PHASE: render" in thumbnail_job
    assert "thumbnail_artwork.png" in thumbnail_job
    assert "thumbnail_packaging" in workflow[:workflow.index("  restore-production:")]
    assert "private_upload_status != 'completed'" in workflow
