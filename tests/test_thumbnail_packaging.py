import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.project import thumbnail_packaging
from modules.project.thumbnail_packaging import (
    THUMBNAIL_QUALITY_CHECKS,
    FFmpegThumbnailComposer,
    ThumbnailConcept,
    ThumbnailConceptDraft,
    ThumbnailPackagingEngine,
    ThumbnailVisualChecks,
    ThumbnailVisualReview,
)
from modules.storyboard.visual_models import VisualWorldBible


def _concepts():
    return ThumbnailConceptDraft(
        concepts=[
            ThumbnailConcept(
                concept_id="ignored-a",
                curiosity_angle="DISCOVERY_REVEAL",
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
                curiosity_angle="PROBLEM_DANGER",
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
                curiosity_angle="UNEXPECTED_MECHANISM",
                visual_concept="A large stickman pirate dramatically swaps an eye patch.",
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


class FakeVisualReviewer:
    def __init__(self, reviews=None):
        self.reviews = list(reviews or [])
        self.contexts = []

    def review(self, *, thumbnail_path, artwork_path, context):
        assert thumbnail_path.is_file()
        assert artwork_path.is_file()
        self.contexts.append(context)
        if self.reviews:
            return self.reviews.pop(0)
        return ThumbnailVisualReview(
            status="PASS",
            checks=ThumbnailVisualChecks(
                **{name: "PASS" for name in THUMBNAIL_QUALITY_CHECKS}
            ),
            rationale="The image, exact text, and topic form a clear mobile-first hook.",
        )


def _review(status, *, failed_check=None, correction=""):
    checks = {name: "PASS" for name in THUMBNAIL_QUALITY_CHECKS}
    if failed_check:
        checks[failed_check] = "FAIL"
    return ThumbnailVisualReview(
        status=status,
        checks=ThumbnailVisualChecks(**checks),
        failure_categories=(
            ["TOO_MUCH_CLUTTER"]
            if failed_check
            else []
        ),
        rationale=f"Visual review status: {status}.",
        correction_prompt=correction,
    )


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
    (project / "visual_world_bible.json").write_text(
        VisualWorldBible(
            topic="Why Do Pirates Wear Eye Patches?",
            historical=True,
            time_period="Early modern maritime era",
            geography="Atlantic sailing routes",
            civilization_or_society="Sailing crews",
            technology_level="Sailing vessels and hand tools",
            built_environment="Wooden sailing ships",
            clothing="Period-appropriate seafaring clothing",
            transportation="Sailing ships",
            tools_and_weapons="Period-appropriate hand tools",
            containers_and_materials="Wood, cloth, and metal",
            architecture="Wooden ship structures",
            natural_environment="Open sea and bright daylight",
            social_context="Shipboard life",
            visual_style="Simple hand-drawn cartoon",
            technology_ceiling="No modern lighting or electronics.",
        ).model_dump_json(),
        encoding="utf-8",
    )
    (project / "video" / "ritzz_test.mp4").write_bytes(b"mock-video")
    return project


def _engine(
    concepts=None,
    artwork=None,
    composer=None,
    reviewer=None,
    *,
    dimensions=None,
):
    return ThumbnailPackagingEngine(
        concept_generator=concepts or FakeConceptGenerator(),
        artwork_generator=artwork or FakeArtworkGenerator(),
        composer=composer or FakeComposer(),
        visual_reviewer=reviewer or FakeVisualReviewer(),
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
    assert generator.contexts[0]["visual_world_bible"]["historical"] is True
    assert {item["curiosity_angle"] for item in first["concepts"]} == {
        "DISCOVERY_REVEAL",
        "PROBLEM_DANGER",
        "UNEXPECTED_MECHANISM",
    }
    assert second == first


def test_changed_thumbnail_inputs_invalidate_saved_concepts(tmp_path):
    project = _project(tmp_path)
    generator = FakeConceptGenerator()
    engine = _engine(concepts=generator)
    first = engine.create_concepts(
        project,
        production_id="production-1",
        project_id="20261005_001",
    )

    metadata_path = project / "metadata_packaging.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["description"] = "Updated description with new viewer promise."
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    second = engine.create_concepts(
        project,
        production_id="production-1",
        project_id="20261005_001",
    )

    assert first["input_fingerprint"] != second["input_fingerprint"]
    assert len(generator.contexts) == 2


def test_visual_reviewer_checks_have_a_fixed_complete_schema():
    assert set(ThumbnailVisualChecks.model_fields) == set(THUMBNAIL_QUALITY_CHECKS)
    with pytest.raises(ValueError):
        ThumbnailVisualChecks(topic_accuracy="PASS")


def test_invalid_thumbnail_concepts_get_one_feedback_guided_retry(tmp_path):
    project = _project(tmp_path)
    invalid = _concepts()
    invalid.concepts[1] = invalid.concepts[1].model_copy(
        update={"text": invalid.concepts[0].text}
    )

    class RetryingGenerator:
        def __init__(self):
            self.contexts = []

        def generate(self, context):
            self.contexts.append(context)
            return invalid if len(self.contexts) == 1 else _concepts()

    generator = RetryingGenerator()
    result = _engine(concepts=generator).create_concepts(
        project,
        production_id="production-1",
        project_id="20261005_001",
    )

    assert result["status"] == "AWAITING_CONCEPT_SELECTION"
    assert len(generator.contexts) == 2
    assert "validation issues" in generator.contexts[1]["qa_feedback"]


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
    assert artifact["qa"]["automated_status"] == "PASS"
    assert artifact["qa"]["overall_status"] == "REVIEW"
    assert artifact["human_review_status"] == "REVIEW"
    assert (project / "video" / "thumbnail.jpg").is_file()
    assert (project / "video" / "thumbnail_artwork.png").is_file()


def test_actionable_visual_failure_repairs_only_selected_artwork_then_passes(tmp_path):
    project = _project(tmp_path)
    artwork_generator = FakeArtworkGenerator()
    reviewer = FakeVisualReviewer(
        [
            _review(
                "FAIL",
                failed_check="clutter",
                correction="Remove the extra background objects; retain the pirate and patch.",
            ),
            _review("PASS"),
        ]
    )
    engine = _engine(artwork=artwork_generator, reviewer=reviewer)
    engine.create_concepts(
        project,
        production_id="production-1",
        project_id="20261005_001",
    )

    result = engine.render_selected(
        project,
        production_id="production-1",
        project_id="20261005_001",
        concept_id="concept-2",
    )

    assert result["status"] == "COMPLETE"
    assert len(artwork_generator.prompts) == 2
    assert "Remove the extra background objects" in artwork_generator.prompts[1]
    assert result["retry_history"][0]["status"] == "FAIL"
    assert result["retry_history"][0]["repair_applied"] is True
    assert result["retry_history"][1]["status"] == "PASS"
    assert all(item["concept_id"] == "concept-2" for item in result["retry_history"])


def test_visual_repair_stops_after_bounded_attempts_and_persists_history(tmp_path):
    project = _project(tmp_path)
    artwork_generator = FakeArtworkGenerator()
    reviewer = FakeVisualReviewer(
        [
            _review("FAIL", failed_check="clutter", correction="Remove clutter."),
            _review("FAIL", failed_check="clutter", correction="Simplify the backdrop."),
            _review("FAIL", failed_check="clutter", correction="Remove remaining clutter."),
        ]
    )
    engine = _engine(artwork=artwork_generator, reviewer=reviewer)
    engine.create_concepts(
        project,
        production_id="production-1",
        project_id="20261005_001",
    )

    with pytest.raises(ValueError, match="after two concept-only repairs"):
        engine.render_selected(
            project,
            production_id="production-1",
            project_id="20261005_001",
            concept_id="concept-2",
        )

    saved = json.loads((project / "thumbnail_packaging.json").read_text())
    assert saved["status"] == "FAILED"
    assert len(artwork_generator.prompts) == 3
    assert len(saved["retry_history"]) == 3
    assert [entry["repair_applied"] for entry in saved["retry_history"]] == [
        True,
        True,
        False,
    ]


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
        concept_id="concept-1",
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
        (
            {"text": "EXTRAORDINARILY LONG HIDDEN PATH"},
            "fit on one readable line",
        ),
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
        if "-f" in command and "rawvideo" in command:
            return SimpleNamespace(
                returncode=0,
                stdout=bytes((30, 30, 30)),
                stderr=b"",
            )
        captured["command"] = command
        captured["kwargs"] = kwargs
        filter_text = command[command.index("-vf") + 1]
        text_file = Path(re.search(r"textfile='([^']+)'", filter_text).group(1))
        captured["rendered_text"] = text_file.read_text(encoding="utf-8")
        output_path = Path(command[-1])
        output_path.write_bytes(b"composited-jpeg")

        return SimpleNamespace(returncode=0, stderr="", stdout=b"")

    monkeypatch.setattr(thumbnail_packaging, "_escape_filter_path", str)
    monkeypatch.setattr(thumbnail_packaging.subprocess, "run", fake_run)
    composer = FFmpegThumbnailComposer(ffmpeg_path="ffmpeg", font_path=font)

    result = composer.compose(artwork, output, "TWO EYES?")

    filter_text = captured["command"][captured["command"].index("-vf") + 1]
    assert "drawtext=" in filter_text
    assert "fontcolor=yellow" in filter_text
    assert "borderw=4:bordercolor=black" in filter_text
    assert "shadowx=4:shadowy=5" in filter_text
    assert f"fontsize={composer.last_layout['font_size']}" in filter_text
    assert composer.last_text_color == "yellow"
    assert composer.last_layout["line_count"] == 1
    assert "box=" not in filter_text
    assert captured["rendered_text"] == "TWO EYES?"
    assert result == output
    assert output.read_bytes() == b"composited-jpeg"


def test_ffmpeg_composer_uses_white_text_on_a_bright_background(
    tmp_path,
    monkeypatch,
):
    artwork = tmp_path / "artwork.png"
    artwork.write_bytes(b"generated-art")
    font = tmp_path / "font.ttf"
    font.write_bytes(b"test-font")

    def fake_run(command, **_kwargs):
        if "-f" in command and "rawvideo" in command:
            return SimpleNamespace(
                returncode=0,
                stdout=bytes((240, 240, 240)),
                stderr=b"",
            )
        Path(command[-1]).write_bytes(b"composited-jpeg")
        return SimpleNamespace(returncode=0, stderr="", stdout=b"")

    monkeypatch.setattr(thumbnail_packaging, "_escape_filter_path", str)
    monkeypatch.setattr(thumbnail_packaging.subprocess, "run", fake_run)
    composer = FFmpegThumbnailComposer(ffmpeg_path="ffmpeg", font_path=font)

    composer.compose(artwork, tmp_path / "thumbnail.jpg", "TWO EYES?")

    assert composer.last_text_color == "white"


def test_visually_similar_thumbnail_concepts_are_rejected(tmp_path):
    project = _project(tmp_path)
    draft = _concepts()
    draft.concepts[1] = draft.concepts[0].model_copy(
        update={
            "concept_id": "near-duplicate",
            "curiosity_angle": "PROBLEM_DANGER",
            "text": "PATCH SECRET",
        }
    )

    with pytest.raises(ValueError, match="visually distinct|differ in focal object"):
        _engine(concepts=FakeConceptGenerator(draft)).create_concepts(
            project,
            production_id="production-1",
            project_id="20261005_001",
        )


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
    assert "rerun_from_stage == 'thumbnail_packaging'" in thumbnail_job
    assert "needs: [metadata-packaging, restore-production]" in thumbnail_job
    assert "fonts-comic-neue" in thumbnail_job
    assert "thumbnail_artwork.png" in thumbnail_job
    assert "thumbnail_packaging" in workflow[:workflow.index("  restore-production:")]
    assert "private_upload_status != 'completed'" in workflow
