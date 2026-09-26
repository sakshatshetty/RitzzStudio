import json
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from modules.video.pipeline_engine import (
    VideoProductionPipeline,
)

from modules.video.pipeline_models import (
    VideoProductionRequest,
    VideoProductionResult,
)
from modules.video.qa_models import SceneQAResult, TechnicalQAResult
from modules.qa.engine import load_project_qa
from modules.image.models import ImageGenerationResult
from modules.storyboard.engine import StoryboardEngine


FFMPEG_AVAILABLE = (
    shutil.which("ffmpeg") is not None
    and shutil.which("ffprobe") is not None
)


pytestmark = pytest.mark.skipif(
    not FFMPEG_AVAILABLE,
    reason="FFmpeg/ffprobe not available",
)


def create_images(
    tmp_path: Path,
) -> Path:
    """
    Create three valid PNG images.
    """

    ffmpeg = shutil.which("ffmpeg")

    assert ffmpeg is not None

    image_directory = (
        tmp_path / "images"
    )

    image_directory.mkdir()

    colors = [
        "red",
        "green",
        "blue",
    ]

    for index, color in enumerate(
        colors,
        start=1,
    ):
        output_file = (
            image_directory
            / f"scene_{index:03d}.png"
        )

        command = [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x180",
            "-frames:v",
            "1",
            str(output_file),
        ]

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0
        assert output_file.exists()
        assert output_file.stat().st_size > 0

    return image_directory


def create_audio(
    tmp_path: Path,
) -> Path:
    """
    Create a valid 3-second WAV file.
    """

    audio_file = (
        tmp_path / "narration.wav"
    )

    sample_rate = 48_000
    duration_seconds = 3
    frame_count = (
        sample_rate
        * duration_seconds
    )

    with wave.open(
        str(audio_file),
        "wb",
    ) as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(
            sample_rate
        )
        audio.writeframes(
            b"\x00\x00"
            * frame_count
        )

    return audio_file


def create_storyboard(
    tmp_path: Path,
    audio_file: Path,
) -> Path:
    """
    Create a three-scene storyboard and
    matching ElevenLabs-style alignment.
    """

    scenes = [
        {
            "scene_id": "scene_001",
            "section_id": "s1",
            "start_seconds": 0.0,
            "duration_seconds": 1.0,
            "narration": (
                "The pirate looks across the sea."
            ),
            "visual_style": "stickman",
            "visual_description": (
                "A pirate standing on a wooden ship."
            ),
            "character_action": "",
            "background": "",
            "props": [],
            "text_overlay": "",
            "camera_motion": "slow_zoom_in",
            "transition": "cut",
            "research_sources": [],
            "image_prompt": (
                "Simple pirate illustration."
            ),
        },
        {
            "scene_id": "scene_002",
            "section_id": "s1",
            "start_seconds": 1.0,
            "duration_seconds": 1.0,
            "narration": (
                "He suddenly notices something."
            ),
            "visual_style": "stickman",
            "visual_description": (
                "The pirate looks surprised."
            ),
            "character_action": "",
            "background": "",
            "props": [],
            "text_overlay": "",
            "camera_motion": "pan_right",
            "transition": "cut",
            "research_sources": [],
            "image_prompt": (
                "Simple surprised pirate illustration."
            ),
        },
        {
            "scene_id": "scene_003",
            "section_id": "s1",
            "start_seconds": 2.0,
            "duration_seconds": 1.0,
            "narration": (
                "The mystery begins."
            ),
            "visual_style": "stickman",
            "visual_description": (
                "The pirate investigates a mystery."
            ),
            "character_action": "",
            "background": "",
            "props": [],
            "text_overlay": "",
            "camera_motion": "static",
            "transition": "cut",
            "research_sources": [],
            "image_prompt": (
                "Simple pirate mystery illustration."
            ),
        },
    ]

    storyboard = {
        "topic": "Why Do Pirates Wear Eye Patches?",
        "target_duration_seconds": 3,
        "scenes": scenes,
        "total_scene_duration_seconds": 3.0,
        "target_scene_duration_seconds": 5.0,
    }

    storyboard_file = (
        tmp_path / "storyboard.json"
    )

    storyboard_file.write_text(
        json.dumps(storyboard),
        encoding="utf-8",
    )

    return storyboard_file


def create_alignment(
    tmp_path: Path,
) -> Path:
    """
    Create alignment whose timing matches
    the three storyboard narrations.
    """

    script = (
        "The pirate looks across the sea. "
        "He suddenly notices something. "
        "The mystery begins."
    )

    characters = list(script)

    starts: list[float] = []
    ends: list[float] = []

    current = 0.0

    for _ in characters:
        starts.append(
            round(current, 3)
        )

        current += (
            3.0 / len(characters)
        )

        ends.append(
            round(current, 3)
        )

    data = {
        "duration_seconds": 3.0,
        "alignment": {
            "characters": characters,
            "character_start_times_seconds": starts,
            "character_end_times_seconds": ends,
        },
    }

    alignment_file = (
        tmp_path
        / "narration_result.json"
    )

    alignment_file.write_text(
        json.dumps(data),
        encoding="utf-8",
    )

    return alignment_file


def test_create_request(
    tmp_path: Path,
) -> None:
    pipeline = VideoProductionPipeline()

    request = pipeline.create_request(
        storyboard_file=(
            tmp_path / "storyboard.json"
        ),
        image_directory=(
            tmp_path / "images"
        ),
        narration_result_file=(
            tmp_path / "narration_result.json"
        ),
        output_directory=(
            tmp_path / "output"
        ),
    )

    assert isinstance(
        request,
        VideoProductionRequest,
    )

    assert request.storyboard_file == str(
        tmp_path / "storyboard.json"
    )

    assert request.image_directory == str(
        tmp_path / "images"
    )

    assert request.narration_result_file == str(
        tmp_path / "narration_result.json"
    )

    assert request.output_directory == str(
        tmp_path / "output"
    )


def test_complete_three_scene_pipeline(
    tmp_path: Path,
) -> None:
    image_directory = create_images(
        tmp_path
    )

    audio_file = create_audio(
        tmp_path
    )

    storyboard_file = create_storyboard(
        tmp_path,
        audio_file,
    )

    alignment_file = create_alignment(
        tmp_path
    )

    output_directory = (
        tmp_path / "output"
    )

    pipeline = VideoProductionPipeline()

    request = pipeline.create_request(
        storyboard_file=storyboard_file,
        image_directory=image_directory,
        narration_result_file=alignment_file,
        audio_file=audio_file,
        output_directory=output_directory,
    )

    result = pipeline.run(
        request
    )

    assert isinstance(
        result,
        VideoProductionResult,
    )

    assert result.status == "completed"

    assert result.scene_count == 3

    assert result.duration_seconds == pytest.approx(
        3.0,
        abs=0.25,
    )

    assert result.video_plan_file is not None
    assert result.synchronized_plan_file is not None
    assert result.motion_plan_file is not None
    assert result.output_video_file is not None

    assert Path(
        result.video_plan_file
    ).exists()

    assert Path(
        result.synchronized_plan_file
    ).exists()

    assert Path(
        result.motion_plan_file
    ).exists()

    output_video = Path(
        result.output_video_file
    )

    assert output_video.exists()

    assert output_video.stat().st_size > 0
    state = json.loads(
        (output_directory / "pipeline_state.json").read_text(encoding="utf-8")
    )
    assert state["stages"]["assembly"]["status"] == "completed"
    assert state["stages"]["synchronization"]["status"] == "completed"
    assert state["stages"]["motion"]["status"] == "completed"
    assert state["stages"]["render"]["status"] == "completed"


def test_image_ai_qa_moves_editorial_and_repairs_impacted_images(tmp_path: Path) -> None:
    image_directory = create_images(tmp_path)
    audio_file = create_audio(tmp_path)
    storyboard_file = create_storyboard(tmp_path, audio_file)
    alignment_file = create_alignment(tmp_path)
    storyboard = StoryboardEngine.load_storyboard(storyboard_file)
    storyboard.scenes[0].text_overlay = "ICONIC"
    StoryboardEngine.save_storyboard(storyboard, storyboard_file)
    review_attempts: dict[str, int] = {}

    class Reviewer:
        def review(self, image_path, scene, editorial_candidates=None):
            assert image_path.is_file()
            assert editorial_candidates is not None
            assert any(candidate["scene_id"] == scene.scene_id for candidate in editorial_candidates)
            review_attempts[scene.scene_id] = review_attempts.get(scene.scene_id, 0) + 1
            if scene.scene_id == "scene_001" and review_attempts[scene.scene_id] == 1:
                return SceneQAResult(
                    scene_id=scene.scene_id,
                    status="FAIL",
                    narration_image="PASS",
                    narration_description="PASS",
                    editorial_context="FAIL",
                    rationale="The callout better fits the next scene.",
                    suggested_editorial_scene_id="scene_002",
                )
            if scene.scene_id == "scene_003" and review_attempts[scene.scene_id] == 1:
                return SceneQAResult(
                    scene_id=scene.scene_id,
                    status="REVIEW",
                    narration_image="REVIEW",
                    narration_description="PASS",
                    editorial_context="PASS",
                    rationale="The pirate's pose is unclear.",
                    correction_prompt="Make the pirate's surprised expression and pointing gesture unmistakable.",
                )
            return SceneQAResult(
                scene_id=scene.scene_id,
                status="PASS",
                narration_image="PASS",
                narration_description="PASS",
                editorial_context="PASS",
                rationale="The image and callout match this scene.",
            )

    class ImageProvider:
        def __init__(self):
            self.generated_scenes: list[str] = []

        def generate(self, request):
            output = Path(request.output_directory) / f"{request.image_id}.png"
            shutil.copyfile(image_directory / "scene_003.png", output)
            self.generated_scenes.append(request.scene_id)
            return ImageGenerationResult(
                image_id=request.image_id,
                scene_id=request.scene_id,
                provider="openai",
                status="completed",
                file_path=str(output),
            )

    provider = ImageProvider()
    pipeline = VideoProductionPipeline(image_reviewer=Reviewer(), image_provider=provider)
    request = pipeline.create_request(
        storyboard_file=storyboard_file,
        image_directory=image_directory,
        narration_result_file=alignment_file,
        audio_file=audio_file,
        output_directory=tmp_path / "output",
        enable_image_ai_qa=True,
    )

    status = pipeline._review_and_repair_images(request, tmp_path)
    updated_storyboard = StoryboardEngine.load_storyboard(storyboard_file)
    report = load_project_qa(tmp_path)
    assert status == "PASS"
    assert [scene.text_overlay for scene in updated_storyboard.scenes] == ["", "ICONIC", ""]
    assert provider.generated_scenes == ["scene_001", "scene_002", "scene_003"]
    assert (tmp_path / "qa" / "image_repair" / "attempt_1" / "originals" / "scene_001.png").is_file()
    assert (tmp_path / "qa" / "image_repair" / "attempt_1" / "originals" / "scene_003.png").is_file()
    image_checks = report.stages["image_editorial_qa"][-1]
    assert image_checks.status == "PASS"
    assert "scene_002.editorial_context" in image_checks.checks
    assert "scene_002.narration_description" in image_checks.checks
    assert [attempt.status for attempt in report.stages["image_editorial_qa"]] == ["FAIL", "PASS"]


def test_pipeline_requests_bounded_sync_repair_for_timeline_drift_review() -> None:
    assert VideoProductionPipeline._has_sync_failures({"timeline_drift": "REVIEW"})
    assert not VideoProductionPipeline._has_sync_failures({"images": "REVIEW"})


def test_pipeline_resynchronizes_and_renders_again_on_timeline_drift_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_directory = create_images(tmp_path)
    audio_file = create_audio(tmp_path)
    storyboard_file = create_storyboard(tmp_path, audio_file)
    alignment_file = create_alignment(tmp_path)
    technical_attempts = 0
    render_attempts = 0

    def run_technical(self, storyboard, plan, audio, video):
        nonlocal technical_attempts
        technical_attempts += 1
        status = "REVIEW" if technical_attempts == 1 else "PASS"
        checks = {
            "images": "PASS",
            "audio": "PASS",
            "scene_order": "PASS",
            "timestamps_monotonic": "PASS",
            "no_gaps_or_overlaps": "PASS",
            "scene_durations": "PASS",
            "duration_consistency": "PASS",
            "video": "PASS",
            "timestamp_coverage": "PASS",
            "timeline_drift": "REVIEW" if status == "REVIEW" else "PASS",
        }
        return TechnicalQAResult(
            status=status,
            checks=checks,
            issues=["Timeline drift needs synchronization."] if status == "REVIEW" else [],
            scene_count=len(plan.clips),
            audio_duration_seconds=3.0,
            video_duration_seconds=3.0,
            maximum_timeline_drift_seconds=1.0 if status == "REVIEW" else 0.0,
        )

    monkeypatch.setattr("modules.video.pipeline_engine.PilotVideoQA.run_technical", run_technical)
    pipeline = VideoProductionPipeline()
    original_render = pipeline.renderer.render

    def count_render(*args, **kwargs):
        nonlocal render_attempts
        render_attempts += 1
        return original_render(*args, **kwargs)

    monkeypatch.setattr(pipeline.renderer, "render", count_render)
    request = pipeline.create_request(
        storyboard_file,
        image_directory,
        alignment_file,
        tmp_path / "output",
        audio_file,
    )

    result = pipeline.run(request)

    assert result.status == "completed"
    assert result.technical_qa_status == "PASS"
    assert technical_attempts == 2
    assert render_attempts == 2
    qa_report = load_project_qa(tmp_path)
    assert qa_report.stages["sync_repair"][-1].status == "PASS"


def test_pipeline_saves_expected_artifacts(
    tmp_path: Path,
) -> None:
    image_directory = create_images(
        tmp_path
    )

    audio_file = create_audio(
        tmp_path
    )

    storyboard_file = create_storyboard(
        tmp_path,
        audio_file,
    )

    alignment_file = create_alignment(
        tmp_path
    )

    output_directory = (
        tmp_path / "output"
    )

    pipeline = VideoProductionPipeline()

    request = pipeline.create_request(
        storyboard_file,
        image_directory,
        alignment_file,
        output_directory,
        audio_file,
    )

    result = pipeline.run(
        request
    )

    assert result.status == "completed"

    assert (
        output_directory
        / "video_plan.json"
    ).exists()

    assert (
        output_directory
        / "synced_video_plan.json"
    ).exists()

    assert (
        output_directory
        / "motion_plan.json"
    ).exists()

    assert (
        output_directory
        / "ritzz_final.mp4"
    ).exists()


def test_pipeline_handles_missing_storyboard(
    tmp_path: Path,
) -> None:
    pipeline = VideoProductionPipeline()

    request = pipeline.create_request(
        storyboard_file=(
            tmp_path
            / "missing_storyboard.json"
        ),
        image_directory=(
            tmp_path / "images"
        ),
        narration_result_file=(
            tmp_path / "alignment.json"
        ),
        output_directory=(
            tmp_path / "output"
        ),
    )

    result = pipeline.run(
        request
    )

    assert result.status == "failed"
    assert result.output_video_file is None
    assert result.error_message is not None


def test_pipeline_handles_missing_images(
    tmp_path: Path,
) -> None:
    audio_file = create_audio(
        tmp_path
    )

    storyboard_file = create_storyboard(
        tmp_path,
        audio_file,
    )

    alignment_file = create_alignment(
        tmp_path
    )

    image_directory = (
        tmp_path / "images"
    )

    image_directory.mkdir()

    pipeline = VideoProductionPipeline()

    request = pipeline.create_request(
        storyboard_file=storyboard_file,
        image_directory=image_directory,
        narration_result_file=alignment_file,
        audio_file=audio_file,
        output_directory=(
            tmp_path / "output"
        ),
    )

    result = pipeline.run(
        request
    )

    assert result.status == "failed"
    assert result.error_message is not None


def test_pipeline_rejects_corrupt_png_before_render(
    tmp_path: Path,
) -> None:
    audio_file = create_audio(tmp_path)
    storyboard_file = create_storyboard(tmp_path, audio_file)
    alignment_file = create_alignment(tmp_path)
    image_directory = tmp_path / "images"
    image_directory.mkdir()
    for index in range(1, 4):
        (image_directory / f"scene_{index:03d}.png").write_bytes(b"not-a-png")

    output_directory = tmp_path / "output"
    result = VideoProductionPipeline().run(
        VideoProductionPipeline().create_request(
            storyboard_file, image_directory, alignment_file, output_directory, audio_file
        )
    )

    assert result.status == "failed"
    assert "Asset validation failed" in (result.error_message or "")


def test_pipeline_uses_custom_output_filename(
    tmp_path: Path,
) -> None:
    image_directory = create_images(
        tmp_path
    )

    audio_file = create_audio(
        tmp_path
    )

    storyboard_file = create_storyboard(
        tmp_path,
        audio_file,
    )

    alignment_file = create_alignment(
        tmp_path
    )

    output_directory = (
        tmp_path / "output"
    )

    custom_output = (
        output_directory
        / "pirates_test.mp4"
    )

    pipeline = VideoProductionPipeline()

    request = pipeline.create_request(
        storyboard_file=storyboard_file,
        image_directory=image_directory,
        narration_result_file=alignment_file,
        audio_file=audio_file,
        output_directory=output_directory,
        output_video_file=custom_output,
    )

    result = pipeline.run(
        request
    )

    assert result.status == "completed"

    assert result.output_video_file == (
        str(custom_output)
    )

    assert custom_output.exists()


def test_pipeline_supports_retry_from_motion_and_records_usage(tmp_path: Path) -> None:
    image_directory = create_images(tmp_path)
    audio_file = create_audio(tmp_path)
    storyboard_file = create_storyboard(tmp_path, audio_file)
    alignment_file = create_alignment(tmp_path)
    output_directory = tmp_path / "output"
    pipeline = VideoProductionPipeline()
    request = pipeline.create_request(storyboard_file, image_directory, alignment_file, output_directory, audio_file)
    assert pipeline.run(request).status == "completed"

    retry = pipeline.create_request(
        storyboard_file, image_directory, alignment_file, output_directory, audio_file,
        retry_from_stage="motion",
    )
    result = pipeline.run(retry)

    assert result.status == "completed"
    state = json.loads((output_directory / "pipeline_state.json").read_text(encoding="utf-8"))
    assert state["stages"]["motion"]["attempts"] == 2
    usage = json.loads((output_directory / "pipeline_usage.json").read_text(encoding="utf-8"))
    assert any(item["stage"] == "render" and "duration_seconds" in item for item in usage["stages"])