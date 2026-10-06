import hashlib
import json
from pathlib import Path

import pytest

from modules.production_state import ProductionStateStore
from modules.project.manager import ProjectManager
from modules.project.packaging import PackagingArtifact, PackagingMetadata
from scripts import run_private_upload_stage


def _valid_probe(**updates):
    result = {
        "has_video": True,
        "has_audio": True,
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "video_codec_name": "h264",
        "video_bit_rate_bps": 10_000_000,
        "duration_seconds": 480.0,
        "audio_duration_seconds": 480.0,
        "audio_channels": 2,
    }
    result.update(updates)
    return result


def _prepare_upload(tmp_path, monkeypatch, *, probe=None, processing_status=None):
    monkeypatch.chdir(tmp_path)
    projects = Path("projects")
    project = ProjectManager(projects).create_project("A private upload test")
    project_directory = ProjectManager(projects).get_project_path(project)
    video_file = project_directory / "video" / "ritzz_test.mp4"
    video_file.parent.mkdir(parents=True, exist_ok=True)
    video_file.write_bytes(b"final 1080p master")
    preview = project_directory / "video" / "preview_360p.mp4"
    preview.write_bytes(b"lower-resolution preview")
    artifact = PackagingArtifact(
        selected_title="Test title",
        metadata=PackagingMetadata(
            description="Test description",
            tags=["test", "video"],
        ),
    )
    (project_directory / "packaging.json").write_text(
        json.dumps(artifact.to_dict()),
        encoding="utf-8",
    )
    artifacts = Path(".pipeline-artifacts")
    artifacts.mkdir()
    state_store = ProductionStateStore(
        artifacts / "production_state.json",
        artifacts,
    )
    state_store.initialize("production-1")
    state_store.start_stage("private_upload")
    state_store.set_private_upload_intent("run-1", 1)
    monkeypatch.setenv("RITZZ_PROJECT_ID", project.project_id)
    monkeypatch.setenv("RITZZ_PRODUCTION_ID", "production-1")
    monkeypatch.setenv("RITZZ_PIPELINE_ARTIFACTS", str(artifacts))
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", "client.json")
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", "token.json")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    class FakeRenderer:
        video_bitrate_bps = 10_000_000

        def _probe_media(self, path):
            assert Path(path) == video_file
            return probe or _valid_probe()

    class FakeProvider:
        def __init__(self):
            self.upload_calls = []
            self.status_calls = []

        def upload_video(self, **kwargs):
            self.upload_calls.append(kwargs)
            return {"video_id": "video-123", "url": "https://youtu.be/video-123"}

        def get_video_processing_status(self, video_id):
            self.status_calls.append(video_id)
            return processing_status or {
                "processing_status": "YOUTUBE_PROCESSING_PENDING",
                "video_id": video_id,
                "duration": "PT8M",
            }

    provider = FakeProvider()
    monkeypatch.setattr(
        run_private_upload_stage,
        "FFmpegVideoRenderer",
        FakeRenderer,
    )
    monkeypatch.setattr(
        run_private_upload_stage,
        "YouTubeProvider",
        lambda *_args: provider,
    )
    return project, project_directory, video_file, provider, state_store, summary


def test_upload_validates_and_uploads_only_exact_master_then_persists_details(
    tmp_path,
    monkeypatch,
):
    _project, project_directory, master, provider, state_store, summary = _prepare_upload(
        tmp_path,
        monkeypatch,
    )

    assert run_private_upload_stage.main() == 0

    assert len(provider.upload_calls) == 1
    assert Path(provider.upload_calls[0]["video_file"]) == master
    assert provider.status_calls == ["video-123"]
    result_path = project_directory / "publishing" / "publish.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["video_id"] == "video-123"
    assert result["upload_status"] == "UPLOAD_COMPLETE"
    assert result["uploaded_at"]
    assert result["upload_details"]["file_path"] == "video/ritzz_test.mp4"
    assert result["upload_details"]["sha256"] == hashlib.sha256(
        master.read_bytes()
    ).hexdigest()
    assert result["upload_details"]["local_master"]["width"] == 1920
    assert result["upload_details"]["local_master"]["height"] == 1080
    assert result["youtube_processing_status"] == "YOUTUBE_PROCESSING_PENDING"
    state = state_store.resume("production-1")
    assert state["youtube_upload"]["video_id"] == "video-123"
    assert state["youtube_upload"]["upload_status"] == "UPLOAD_COMPLETE"
    summary_text = summary.read_text(encoding="utf-8")
    assert "**LOCAL MASTER**" in summary_text
    assert "**YOUTUBE**" in summary_text
    assert "YOUTUBE_PROCESSING_PENDING" in summary_text


def test_lower_resolution_master_fails_before_youtube_upload(
    tmp_path,
    monkeypatch,
):
    _, _, _, provider, _, _ = _prepare_upload(
        tmp_path,
        monkeypatch,
        probe=_valid_probe(width=640, height=360),
    )

    with pytest.raises(ValueError, match="1920x1080"):
        run_private_upload_stage.main()

    assert provider.upload_calls == []
    assert provider.status_calls == []


@pytest.mark.parametrize(
    ("processing_status", "expected", "error"),
    [
        (
            {
                "processing_status": "YOUTUBE_PROCESSING_FAILED",
                "processing_error": "codec rejected",
            },
            "YOUTUBE_PROCESSING_FAILED",
            "codec rejected",
        ),
        (
            {
                "processing_status": "YOUTUBE_PROCESSING_PENDING",
            },
            "YOUTUBE_PROCESSING_PENDING",
            None,
        ),
    ],
)
def test_youtube_processing_status_does_not_fail_or_repeat_upload(
    tmp_path,
    monkeypatch,
    processing_status,
    expected,
    error,
):
    _, project_directory, _, provider, _, _ = _prepare_upload(
        tmp_path,
        monkeypatch,
        processing_status=processing_status,
    )

    assert run_private_upload_stage.main() == 0

    result_path = project_directory / "publishing" / "publish.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["publish_status"] == "PRIVATE"
    assert result["upload_status"] == "UPLOAD_COMPLETE"
    assert result["youtube_processing_status"] == expected
    assert result["youtube_processing_error"] == error
    assert len(provider.upload_calls) == 1
    assert len(provider.status_calls) == 1


def test_private_upload_workflow_installs_ffmpeg_before_validating_master():
    workflow = Path(".github/workflows/ritzz-pipeline.yml").read_text(
        encoding="utf-8"
    )
    private_upload_job = workflow[workflow.index("  private-upload:"):]
    install_step = private_upload_job.index(
        "Install FFmpeg for upload-master validation"
    )
    upload_step = private_upload_job.index("- name: Upload test video privately")

    assert install_step < upload_step
    assert "sudo apt-get install --yes --no-install-recommends ffmpeg" in (
        private_upload_job[install_step:upload_step]
    )


def test_resume_with_saved_video_id_skips_upload_even_when_processing_pending(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    project = ProjectManager(Path("projects")).create_project("Existing upload")
    project_directory = ProjectManager(Path("projects")).get_project_path(project)
    publish_directory = project_directory / "publishing"
    publish_directory.mkdir(parents=True)
    (publish_directory / "publish.json").write_text(
        json.dumps(
            {
                "publish_status": "PRIVATE",
                "video_id": "already-uploaded",
                "url": "https://youtu.be/already-uploaded",
                "title": "Existing upload",
                "upload_status": "UPLOAD_COMPLETE",
                "uploaded_at": "2026-10-05T00:00:00+00:00",
                "upload_details": {
                    "file_path": "video/ritzz_test.mp4",
                    "sha256": "saved-hash",
                    "local_master": {"width": 1920, "height": 1080},
                },
                "youtube_processing_status": "YOUTUBE_PROCESSING_PENDING",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RITZZ_PROJECT_ID", project.project_id)
    monkeypatch.setattr(
        run_private_upload_stage,
        "YouTubeProvider",
        lambda *_args: pytest.fail("Resume must not contact upload provider."),
    )

    assert run_private_upload_stage.main() == 0


def test_render_and_upload_jobs_share_configured_master_bitrate():
    workflow = Path(".github/workflows/ritzz-pipeline.yml").read_text(
        encoding="utf-8"
    )
    setting = "RITZZ_VIDEO_BITRATE: ${{ vars.RITZZ_VIDEO_BITRATE || '10M' }}"
    assert workflow.count(setting) == 2


def test_render_failure_preserves_image_qa_report_before_technical_qa():
    workflow = Path(".github/workflows/ritzz-pipeline.yml").read_text(
        encoding="utf-8"
    )
    assert (
        "grep -Eq '\"(image_editorial_qa|technical_qa)\"' \"$qa_report\""
        in workflow
    )
    assert (
        "path: .pipeline-artifacts/render_qa_report.json"
        in workflow
    )
