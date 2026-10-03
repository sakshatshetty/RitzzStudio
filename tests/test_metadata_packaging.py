import json
from pathlib import Path

import pytest

from modules.production_state import PIPELINE_STAGES, ProductionStateStore
from modules.project import metadata_packaging
from modules.project.manager import ProjectManager
from modules.project.metadata_packaging import (
    METADATA_FILENAME,
    GeneratedVideoMetadata,
    MetadataPackagingEngine,
)
from scripts import run_metadata_packaging


def _generated_metadata(**updates):
    payload = {
        "title_options": [
            {
                "title": "How Moonlight Creates a Rainbow at Night",
                "rationale": "Explains the unusual cause directly.",
            },
            {
                "title": "The Science Behind a Moonbow",
                "rationale": "Names the phenomenon and promises an explanation.",
            },
            {
                "title": "Why Moonbows Appear After Dark",
                "rationale": "Creates curiosity without overstating the video.",
            },
        ],
        "recommended_title": "The Science Behind a Moonbow",
        "title_rationale": "It names the real phenomenon and matches the explanation.",
        "description": (
            "A moonbow is a rainbow formed by moonlight, and it can be difficult to see. "
            "This video explains how water droplets bend moonlight and why these pale arcs "
            "appear only under the right night-sky conditions."
        ),
        "tags": [
            "moonbow science",
            "moonlight rainbow",
            "water droplets",
            "night sky phenomenon",
        ],
    }
    payload.update(updates)
    return GeneratedVideoMetadata.model_validate(payload)


class FakeGenerator:
    def __init__(self, drafts=None):
        self.drafts = list(drafts or [_generated_metadata()])
        self.contexts = []

    def generate(self, context):
        self.contexts.append(context)
        result = self.drafts.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _project(tmp_path: Path, *, semantic_status="REVIEW"):
    manager = ProjectManager(tmp_path / "projects")
    project = manager.create_project("Why do moonbows appear at night?")
    project_path = manager.get_project_path(project)
    (project_path / "topic_selection.json").write_text(
        json.dumps(
            {
                "topic": "Why do moonbows appear at night?",
                "candidate_id": "moonbow-1",
            }
        ),
        encoding="utf-8",
    )
    (project_path / "research").mkdir(parents=True, exist_ok=True)
    (project_path / "research" / "research.json").write_text(
        json.dumps(
            {
                "topic": "Why do moonbows appear at night?",
                "key_facts": [
                    {
                        "fact": "Moonlight refracts through water droplets to form a moonbow.",
                        "sources": ["source-1"],
                    }
                ],
                "sources": [{"id": "source-1", "title": "Atmospheric optics"}],
            }
        ),
        encoding="utf-8",
    )
    (project_path / "outline").mkdir(parents=True, exist_ok=True)
    (project_path / "outline" / "outline.json").write_text(
        json.dumps(
            {
                "topic": "Why do moonbows appear at night?",
                "sections": [{"title": "The light and droplets"}],
            }
        ),
        encoding="utf-8",
    )
    (project_path / "script").mkdir(parents=True, exist_ok=True)
    script = {
        "topic": "Why do moonbows appear at night?",
        "sections": [
            {
                "title": "Opening",
                "narration": "A moonbow is a rainbow formed by moonlight.",
            },
            {
                "title": "The explanation",
                "narration": "Water droplets bend the reflected light into a pale arc.",
            },
        ],
    }
    (project_path / "script" / "script.json").write_text(
        json.dumps(script), encoding="utf-8"
    )
    (project_path / "storyboard").mkdir(parents=True, exist_ok=True)
    (project_path / "storyboard" / "storyboard_audio_timed.json").write_text(
        json.dumps(
            {
                "topic": "Why do moonbows appear at night?",
                "scenes": [
                    {
                        "narration": "Water droplets bend the reflected light.",
                        "visual_description": "Moonlight passing through water droplets.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (project_path / "video").mkdir(parents=True, exist_ok=True)
    (project_path / "video" / "ritzz_test.mp4").write_bytes(b"rendered video")
    (project_path / "qa").mkdir(parents=True, exist_ok=True)
    (project_path / "qa" / "qa_report.json").write_text(
        json.dumps(
            {
                "stages": {
                    "technical_qa": [{"status": "PASS"}],
                    "rendered_semantic_qa": [{"status": semantic_status}],
                }
            }
        ),
        encoding="utf-8",
    )
    (project_path / "packaging.json").write_text(
        json.dumps(
            {
                "selected_title": "Early draft",
                "opportunity_context": {
                    "provider": "vidiq",
                    "report_id": "report-1",
                    "candidate_id": "moonbow-1",
                    "primary_keyword": "moonbow",
                    "related_keywords": ["moonbow science", "moonlight rainbow"],
                    "related_questions": ["How does a moonbow form?"],
                    "evidence": {"search_volume": 350},
                },
            }
        ),
        encoding="utf-8",
    )
    return project, project_path


def _render_metadata():
    return {
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "duration_seconds": 480.0,
    }


def test_packages_from_finished_script_research_storyboard_and_cached_vidiq(tmp_path):
    project, project_path = _project(tmp_path)
    generator = FakeGenerator()

    result = MetadataPackagingEngine(generator).package(
        project_path,
        production_id="production-1",
        project_id=project.project_id,
        render_metadata=_render_metadata(),
    )

    context = generator.contexts[0]
    assert context["final_script"]["full_narration"].startswith("A moonbow is")
    assert context["research"]["key_facts"]
    assert context["outline"]["sections"]
    assert context["final_storyboard"]["scenes"]
    assert result["status"] == "COMPLETE"
    assert result["approved_topic"] == "Why do moonbows appear at night?"
    assert result["vidiq_evidence"]["source"] == "cached_discovery"
    assert result["vidiq_evidence"]["primary_keyword"] == "moonbow"
    assert result["render_metadata"] == _render_metadata()
    assert (project_path / METADATA_FILENAME).is_file()


def test_title_options_and_final_selected_title_are_persisted(tmp_path):
    project, project_path = _project(tmp_path)

    artifact = MetadataPackagingEngine(FakeGenerator()).package(
        project_path,
        production_id="production-1",
        project_id=project.project_id,
        render_metadata=_render_metadata(),
    )

    assert 3 <= len(artifact["title_options"]) <= 5
    assert artifact["selected_title"] == artifact["recommended_title"]
    assert artifact["selected_title"] in {
        item["title"] for item in artifact["title_options"]
    }
    assert artifact["title_rationale"]
    upload_package = json.loads((project_path / "packaging.json").read_text())
    assert upload_package["selected_title"] == artifact["selected_title"]
    assert upload_package["metadata"]["description"] == artifact["description"]
    assert upload_package["metadata"]["tags"] == artifact["tags"]


def test_metadata_does_not_generate_thumbnail_or_call_discovery(tmp_path):
    project, project_path = _project(tmp_path)
    generator = FakeGenerator()

    MetadataPackagingEngine(generator).package(
        project_path,
        production_id="production-1",
        project_id=project.project_id,
        render_metadata=_render_metadata(),
    )

    assert len(generator.contexts) == 1
    assert not (project_path / "video" / "thumbnail.jpg").exists()
    assert not (project_path / "topic_candidates.json").exists()


def test_semantic_review_is_preserved_but_semantic_fail_blocks_metadata(tmp_path):
    project, project_path = _project(tmp_path, semantic_status="FAIL")
    generator = FakeGenerator()

    with pytest.raises(ValueError, match="semantic QA failed"):
        MetadataPackagingEngine(generator).package(
            project_path,
            production_id="production-1",
            project_id=project.project_id,
            render_metadata=_render_metadata(),
        )
    assert not generator.contexts
    artifact = json.loads((project_path / METADATA_FILENAME).read_text())
    assert artifact["status"] == "FAILED"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "description",
            "Moonbows form from moonlight and water droplets, which makes a visible arc possible but",
            "incomplete",
        ),
        (
            "description",
            "A moonbow is a rainbow formed by moonlight. A moonbow is a rainbow formed by moonlight.",
            "duplicate sentences",
        ),
        (
            "description",
            (
                "The Science Behind a Moonbow explains the light. "
                "The Science Behind a Moonbow also explains the droplets."
            ),
            "repeats the selected title",
        ),
        (
            "description",
            (
                "Moonbows form when moonlight passes through water droplets. "
                "They appear as pale rainbows in a dark sky. "
                "Moonbows form when moonlight passes through water droplets."
            ),
            "duplicate sentences",
        ),
        (
            "description",
            (
                "A moonbow is a pale rainbow formed by moonlight and water droplets.\n\n"
                "A moonbow is a pale rainbow formed by moonlight and water droplets."
            ),
            "duplicate paragraphs",
        ),
        (
            "description",
            (
                "A moonbow forms in moonlight. A moonbow needs water droplets. "
                "A moonbow appears pale in the night sky. A moonbow can fade as clouds move."
            ),
            "vidIQ keyword excessively",
        ),
        ("description", "This is a complete placeholder description for the topic. TODO", "placeholder"),
        ("tags", ["moonbow", "moonlight rainbow"], "meaningful search phrase"),
        ("tags", ["science behind", "moonbow science"], "title-tokenized"),
        ("tags", ["moonbow science", "soccer tactics"], "unrelated"),
        (
            "description",
            "Moonbows last 99 years and are formed by moonlight and water droplets.",
            "unsupported",
        ),
    ],
)
def test_invalid_generated_metadata_is_retried_then_rejected(
    tmp_path,
    field,
    value,
    message,
):
    project, project_path = _project(tmp_path)
    invalid = _generated_metadata(**{field: value})
    generator = FakeGenerator([invalid, invalid])

    with pytest.raises(ValueError, match=message):
        MetadataPackagingEngine(generator).package(
            project_path,
            production_id="production-1",
            project_id=project.project_id,
            render_metadata=_render_metadata(),
        )

    assert len(generator.contexts) == 2
    artifact = json.loads((project_path / METADATA_FILENAME).read_text())
    assert artifact["status"] == "FAILED"


def test_completed_metadata_is_reused_without_calling_gpt_again(tmp_path):
    project, project_path = _project(tmp_path)
    original = MetadataPackagingEngine(FakeGenerator()).package(
        project_path,
        production_id="production-1",
        project_id=project.project_id,
        render_metadata=_render_metadata(),
    )

    class MustNotGenerate:
        def generate(self, context):
            del context
            pytest.fail("Completed metadata must be reused.")

    resumed = MetadataPackagingEngine(MustNotGenerate()).package(
        project_path,
        production_id="production-1",
        project_id=project.project_id,
        render_metadata=_render_metadata(),
    )

    assert resumed == original
    assert resumed["status"] == "COMPLETE"


def test_failed_metadata_is_retried_and_successful_result_replaces_it(tmp_path):
    project, project_path = _project(tmp_path)
    first_generator = FakeGenerator([RuntimeError("temporary provider failure")])
    with pytest.raises(RuntimeError, match="temporary provider failure"):
        MetadataPackagingEngine(first_generator).package(
            project_path,
            production_id="production-1",
            project_id=project.project_id,
            render_metadata=_render_metadata(),
        )

    retry_generator = FakeGenerator()
    retried = MetadataPackagingEngine(retry_generator).package(
        project_path,
        production_id="production-1",
        project_id=project.project_id,
        render_metadata=_render_metadata(),
    )

    assert retried["status"] == "COMPLETE"
    assert retried["attempts"] == 2
    assert len(retry_generator.contexts) == 1


def test_metadata_packaging_stage_follows_render_before_final_approval():
    from pathlib import Path

    workflow = Path(".github/workflows/ritzz-pipeline.yml").read_text(encoding="utf-8")
    render = workflow.index("  render-video:")
    video_approval = workflow.index("  video-approval:")
    metadata = workflow.index("  metadata-packaging:")
    final_approval = workflow.index("  packaging-approval:")
    private_upload = workflow.index("  private-upload:")

    assert render < video_approval < metadata < final_approval < private_upload
    assert "needs: [video-approval, render-video, restore-production]" in workflow
    assert "needs: [metadata-packaging, restore-production]" in workflow
    assert "- metadata_packaging" in workflow


def test_production_state_migrates_existing_state_with_metadata_stage(tmp_path):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    store = ProductionStateStore(artifact_root / "production_state.json", artifact_root)
    state = store.initialize("production-1")
    state["stages"].pop("metadata_packaging")
    store.state_file.write_text(json.dumps(state), encoding="utf-8")

    resumed = store.resume("production-1")

    assert tuple(resumed["stages"]) == PIPELINE_STAGES
    assert resumed["stages"]["metadata_packaging"]["status"] == "pending"


def test_runner_requires_render_checkpoint_and_records_complete_metadata_stage(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    artifacts = tmp_path / ".pipeline-artifacts"
    artifacts.mkdir()
    store = ProductionStateStore(artifacts / "production_state.json", artifacts)
    store.initialize("production-1")
    rendered_marker = artifacts / "rendered.json"
    rendered_marker.write_text("{}", encoding="utf-8")
    store.start_stage("render_video")
    project, _ = _project(tmp_path)
    store.complete_stage(
        "render_video",
        ["rendered.json"],
        project_id=project.project_id,
    )
    monkeypatch.setenv("RITZZ_PRODUCTION_ID", "production-1")
    monkeypatch.setenv("RITZZ_PROJECT_ID", project.project_id)
    monkeypatch.setenv("RITZZ_PIPELINE_ARTIFACTS", str(artifacts))
    summary_file = tmp_path / "github-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    monkeypatch.setenv("GITHUB_REPOSITORY", "sakshatshetty/RitzzStudio")
    monkeypatch.setenv("RITZZ_REVIEW_RUN_ID", "12345")

    class FakeRenderer:
        def _probe_media(self, video_path):
            assert video_path.name == "ritzz_test.mp4"
            return _render_metadata()

    monkeypatch.setattr(run_metadata_packaging, "FFmpegVideoRenderer", FakeRenderer)
    generator = FakeGenerator()
    monkeypatch.setattr(
        run_metadata_packaging,
        "MetadataPackagingEngine",
        lambda: metadata_packaging.MetadataPackagingEngine(generator),
    )

    assert run_metadata_packaging.main() == 0
    first = json.loads((artifacts / METADATA_FILENAME).read_text(encoding="utf-8"))
    final_state = store.resume("production-1")
    assert final_state["stages"]["metadata_packaging"]["status"] == "completed"
    assert (artifacts / METADATA_FILENAME).is_file()
    assert (artifacts / "rendered-project.tar.gz").is_file()
    assert first["status"] == "COMPLETE"
    assert first["selected_title"] == "The Science Behind a Moonbow"
    assert first["vidiq_evidence"]["source"] == "cached_discovery"
    assert (
        "[Open rendered video and artifacts]"
        "(https://github.com/sakshatshetty/RitzzStudio/actions/runs/12345)"
        in summary_file.read_text(encoding="utf-8")
    )

    assert run_metadata_packaging.main() == 0
    assert len(generator.contexts) == 1


def test_runner_marks_stage_failed_when_existing_metadata_json_is_malformed(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    artifacts = tmp_path / ".pipeline-artifacts"
    artifacts.mkdir()
    store = ProductionStateStore(artifacts / "production_state.json", artifacts)
    store.initialize("production-1")
    (artifacts / "rendered.json").write_text("{}", encoding="utf-8")
    project, project_path = _project(tmp_path)
    store.start_stage("render_video")
    store.complete_stage(
        "render_video",
        ["rendered.json"],
        project_id=project.project_id,
    )
    (project_path / METADATA_FILENAME).write_text("{invalid", encoding="utf-8")
    monkeypatch.setenv("RITZZ_PRODUCTION_ID", "production-1")
    monkeypatch.setenv("RITZZ_PROJECT_ID", project.project_id)
    monkeypatch.setenv("RITZZ_PIPELINE_ARTIFACTS", str(artifacts))

    class FakeRenderer:
        def _probe_media(self, video_path):
            assert video_path.name == "ritzz_test.mp4"
            return _render_metadata()

    monkeypatch.setattr(run_metadata_packaging, "FFmpegVideoRenderer", FakeRenderer)

    with pytest.raises(ValueError, match="Metadata source is unreadable"):
        run_metadata_packaging.main()

    failed_state = store.resume("production-1")
    assert failed_state["stages"]["metadata_packaging"]["status"] == "failed"
    failed_artifact = json.loads(
        (artifacts / METADATA_FILENAME).read_text(encoding="utf-8")
    )
    assert failed_artifact["status"] == "FAILED"
    assert failed_artifact["project_id"] == project.project_id
