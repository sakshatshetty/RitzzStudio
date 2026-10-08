import hashlib
import json
from types import SimpleNamespace

import pytest

from modules.project.manager import ProjectManager
from scripts import run_render_stage
from scripts.run_render_stage import (
    _copy_supplied_thumbnail,
    _reject_semantic_qa_fail,
    _reuse_or_create_thumbnail,
    _validate_production_render_format,
)


def test_production_render_format_requires_exact_resolution_fps_and_aspect_ratio():
    _validate_production_render_format(
        {
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "video_codec_name": "h264",
            "video_bit_rate_bps": 10_000_000,
        }
    )


@pytest.mark.parametrize(
    ("probe", "message"),
    [
        ({"width": 1280, "height": 720, "fps": 30.0}, "1920x1080"),
        ({"width": 1920, "height": 1080, "fps": 29.97}, "30 FPS"),
        ({"width": 1920, "height": 1088, "fps": 30.0}, "1920x1080"),
        (
            {
                "width": 1920,
                "height": 1080,
                "fps": 30.0,
                "video_codec_name": "hevc",
                "video_bit_rate_bps": 10_000_000,
            },
            "H.264",
        ),
        (
            {
                "width": 1920,
                "height": 1080,
                "fps": 30.0,
                "video_codec_name": "h264",
                "video_bit_rate_bps": 1_150_000,
            },
            "bitrate",
        ),
    ],
)
def test_production_render_format_rejects_nonstandard_output(probe, message):
    with pytest.raises(RuntimeError, match=message):
        _validate_production_render_format(probe)


def test_semantic_qa_fail_blocks_but_review_is_allowed_for_human_review():
    with pytest.raises(RuntimeError, match="semantic QA found a clear"):
        _reject_semantic_qa_fail("FAIL")

    _reject_semantic_qa_fail("REVIEW")
    _reject_semantic_qa_fail("PASS")


def test_existing_thumbnail_is_reused_without_regeneration(tmp_path, monkeypatch):
    thumbnail = tmp_path / "thumbnail.jpg"
    thumbnail.write_bytes(b"existing")
    monkeypatch.setattr(
        "scripts.run_render_stage.create_thumbnail",
        lambda *_args, **_kwargs: pytest.fail("Existing thumbnail must be reused."),
    )

    result = _reuse_or_create_thumbnail(
        thumbnail,
        tmp_path / "scene.png",
        "Title",
        probe_media=lambda _path: {"width": 1280, "height": 720},
    )

    assert result == thumbnail
    assert thumbnail.read_bytes() == b"existing"


def test_invalid_existing_thumbnail_is_not_silently_replaced(tmp_path, monkeypatch):
    thumbnail = tmp_path / "thumbnail.jpg"
    thumbnail.write_bytes(b"existing")
    monkeypatch.setattr(
        "scripts.run_render_stage.create_thumbnail",
        lambda *_args, **_kwargs: pytest.fail("Invalid thumbnail must not be overwritten."),
    )

    with pytest.raises(RuntimeError, match="must remain 1280x720"):
        _reuse_or_create_thumbnail(
            thumbnail,
            tmp_path / "scene.png",
            "Title",
            probe_media=lambda _path: {"width": 640, "height": 360},
        )


@pytest.mark.parametrize(
    ("width", "height", "accepted"),
    [
        (1280, 720, True),
        (1672, 941, True),
        (1672, 945, False),
    ],
)
def test_supplied_thumbnail_is_copied_exactly_without_generation(
    tmp_path,
    monkeypatch,
    width,
    height,
    accepted,
):
    project_directory = tmp_path / "project"
    source_directory = project_directory / "creative_input"
    source_directory.mkdir(parents=True)
    source = source_directory / "thumbnail.png"
    source.write_bytes(b"supplied PNG bytes")
    (source_directory / "acceptance.json").write_text(
        json.dumps(
            {
                "status": "ACCEPTED",
                "manifest": {"thumbnail_file": "thumbnail.png"},
                "source_files_sha256": {
                    "thumbnail.png": hashlib.sha256(
                        b"supplied PNG bytes"
                    ).hexdigest()
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.run_render_stage.inspect_image_asset",
        lambda _path: SimpleNamespace(width=width, height=height),
    )

    if not accepted:
        with pytest.raises(RuntimeError, match="one-pixel rounding"):
            _copy_supplied_thumbnail(project_directory, tmp_path / "video")
        return

    result = _copy_supplied_thumbnail(project_directory, tmp_path / "video")
    assert result == tmp_path / "video" / "thumbnail.png"
    assert result.read_bytes() == source.read_bytes()


def test_main_generates_thumbnail_after_successful_render(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project_manager = ProjectManager(tmp_path / "projects")
    project = project_manager.create_project("Thumbnail generation test")
    project_directory = project_manager.get_project_path(project)
    storyboard_directory = project_directory / "storyboard"
    image_directory = project_directory / "images"
    storyboard_directory.mkdir(parents=True, exist_ok=True)
    image_directory.mkdir(parents=True, exist_ok=True)
    (storyboard_directory / "storyboard_audio_timed.json").write_text(
        json.dumps(
            {
                "topic": "Test topic",
                "target_duration_seconds": 5,
                "total_scene_duration_seconds": 5,
                "scenes": [
                    {
                        "scene_id": "scene_001",
                        "section_id": "intro",
                        "start_seconds": 0,
                        "duration_seconds": 5,
                        "narration": "A test scene.",
                        "visual_description": "A clearly described test scene.",
                        "image_prompt": "A simple test scene illustration.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (image_directory / "scene_001.png").write_bytes(b"scene image")
    (project_directory / "packaging.json").write_text(
        json.dumps({"selected_title": "Test Thumbnail Title"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("RITZZ_PROJECT_ID", project.project_id)

    class FakePipeline:
        def __init__(self):
            self.renderer = SimpleNamespace(
                _probe_media=lambda _path: {"width": 1280, "height": 720}
            )

        def create_request(self, **kwargs):
            assert kwargs["enable_image_ai_qa"] is True
            return object()

        def run(self, _request):
            return SimpleNamespace(
                status="completed",
                technical_qa_status="PASS",
                output_video_file="video/ritzz_test.mp4",
                error_message=None,
            )

    monkeypatch.setattr(run_render_stage, "VideoProductionPipeline", FakePipeline)

    def create_thumbnail(_source, output, _title):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"thumbnail")
        return output

    monkeypatch.setattr(run_render_stage, "create_thumbnail", create_thumbnail)

    assert run_render_stage.main() == 0
    assert (project_directory / "video" / "thumbnail.jpg").read_bytes() == b"thumbnail"
