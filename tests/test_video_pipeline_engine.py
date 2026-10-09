import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from modules.image.models import ImageGenerationResult
from modules.qa.engine import load_project_qa
from modules.storyboard.engine import StoryboardEngine
from modules.storyboard.visual_models import (
    SceneVisualContract,
    VisualWorldBible,
)
from modules.video.pipeline_engine import (
    VideoProductionPipeline,
)
from modules.video.pipeline_models import (
    VideoProductionRequest,
    VideoProductionResult,
)
from modules.video.qa_models import QAStatus, SceneQAResult, TechnicalQAResult

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
    image_size = "320x180"

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
            f"color=c={color}:s={image_size}",
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
    Create a valid 12-second WAV file.
    """

    audio_file = (
        tmp_path / "narration.wav"
    )

    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None
    completed = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=12",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(audio_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

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
            "duration_seconds": 4.0,
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
            "callout_not_warranted": True,
            "callout_not_warranted_reason": "This opening scene is context-setting.",
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
            "start_seconds": 4.0,
            "duration_seconds": 4.0,
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
            "callout_not_warranted": True,
            "callout_not_warranted_reason": "This is a transitional reaction beat.",
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
            "start_seconds": 8.0,
            "duration_seconds": 4.0,
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
            "callout_not_warranted": True,
            "callout_not_warranted_reason": "This visual is a brief story bridge.",
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
        "target_duration_seconds": 12,
        "scenes": scenes,
        "total_scene_duration_seconds": 12.0,
        "target_scene_duration_seconds": 4.0,
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

    sections = [
        "The pirate looks across the sea.",
        "He suddenly notices something.",
        "The mystery begins.",
    ]
    characters: list[str] = []

    starts: list[float] = []
    ends: list[float] = []

    current = 0.0
    for index, section in enumerate(sections):
        step = 4.0 / len(section)
        for character_index, character in enumerate(section):
            characters.append(character)
            starts.append(round(current + character_index * step, 3))
            ends.append(round(current + (character_index + 1) * step, 3))
        current += 4.0
        if index + 1 < len(sections):
            characters.append(" ")
            starts.append(round(current, 3))
            ends.append(round(current, 3))

    data = {
        "duration_seconds": 12.0,
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
        12.0,
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


def test_image_ai_qa_ignores_legacy_editorial_fields_and_repairs_visual_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RITZZ_QA_IMAGE_WIDTH", "320")
    monkeypatch.setenv("RITZZ_QA_IMAGE_HEIGHT", "180")
    image_directory = create_images(tmp_path)
    audio_file = create_audio(tmp_path)
    storyboard_file = create_storyboard(tmp_path, audio_file)
    alignment_file = create_alignment(tmp_path)
    storyboard = StoryboardEngine.load_storyboard(storyboard_file)
    storyboard.scenes[0].text_overlay = "ICONIC"
    storyboard.scenes[0].callout_not_warranted = False
    storyboard.scenes[0].callout_not_warranted_reason = None
    StoryboardEngine.save_storyboard(storyboard, storyboard_file)
    review_attempts: dict[str, int] = {}

    class Reviewer:
        def review(self, image_path, scene, editorial_candidates=None):
            assert image_path.is_file()
            assert editorial_candidates is None
            review_attempts[scene.scene_id] = review_attempts.get(scene.scene_id, 0) + 1
            if scene.scene_id == "scene_001" and review_attempts[scene.scene_id] == 1:
                return SceneQAResult(
                    scene_id=scene.scene_id,
                    status="PASS",
                    narration_image="PASS",
                    narration_description="PASS",
                    editorial_obstruction="FAIL",
                    editorial_safe_space="FAIL",
                    rationale="Legacy text fields are not semantic QA criteria.",
                    suggested_editorial_scene_id="scene_002",
                    failure_category="EDITORIAL_OVER_FACE",
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
                    failure_category="WRONG_ACTION",
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
            self.prompts: list[str] = []

        def generate(self, request):
            output = Path(request.output_directory) / f"{request.image_id}.png"
            shutil.copyfile(image_directory / f"{request.scene_id}.png", output)
            self.generated_scenes.append(request.scene_id)
            self.prompts.append(request.prompt)
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
    assert [scene.text_overlay for scene in updated_storyboard.scenes] == ["ICONIC", "", ""]
    assert provider.generated_scenes == ["scene_003"]
    assert not (tmp_path / "qa" / "image_repair" / "attempt_1" / "originals" / "scene_001.png").exists()
    assert (tmp_path / "qa" / "image_repair" / "attempt_1" / "originals" / "scene_003.png").is_file()
    repair_history = json.loads(
        (tmp_path / "qa" / "visual_repair_history.json").read_text(
            encoding="utf-8"
        )
    )
    scene_003_repair = repair_history["scenes"]["scene_003"]["attempts"][0]
    assert scene_003_repair["failure_category"] == "WRONG_ACTION"
    assert scene_003_repair["verification"]["status"] == "PASS"
    assert "make the action the primary focal point" in provider.prompts[-1]
    image_checks = report.stages["image_semantic_qa"][-1]
    assert image_checks.status == "PASS"
    assert "scene_002.narration_description" in image_checks.checks
    assert not any("editorial" in name for name in image_checks.checks)
    assert [attempt.status for attempt in report.stages["image_semantic_qa"]] == ["REVIEW", "PASS"]


def test_image_ai_qa_batches_with_bounded_concurrency_and_retries_failed_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RITZZ_QA_IMAGE_WIDTH", "320")
    monkeypatch.setenv("RITZZ_QA_IMAGE_HEIGHT", "180")
    monkeypatch.setenv("RITZZ_SEMANTIC_QA_BATCH_SIZE", "1")
    monkeypatch.setenv("RITZZ_SEMANTIC_QA_CONCURRENCY", "2")
    monkeypatch.setenv("RITZZ_SEMANTIC_QA_BATCH_RETRIES", "1")
    image_directory = create_images(tmp_path)
    audio_file = create_audio(tmp_path)
    storyboard_file = create_storyboard(tmp_path, audio_file)
    alignment_file = create_alignment(tmp_path)

    class Reviewer:
        def __init__(self) -> None:
            self.lock = threading.Lock()
            self.active = 0
            self.maximum_active = 0
            self.calls_by_scene: dict[str, int] = {}

        def review_batch(self, items):
            with self.lock:
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
                scene_ids = [scene.scene_id for _, scene in items]
                for scene_id in scene_ids:
                    self.calls_by_scene[scene_id] = (
                        self.calls_by_scene.get(scene_id, 0) + 1
                    )
                should_retry = (
                    scene_ids == ["scene_002"]
                    and self.calls_by_scene["scene_002"] == 1
                )
            try:
                time.sleep(0.05)
                if should_retry:
                    raise RuntimeError("temporary reviewer failure")
                return [
                    SceneQAResult(
                        scene_id=scene.scene_id,
                        status="PASS",
                        narration_image="PASS",
                        narration_description="PASS",
                        editorial_context="PASS",
                        rationale=f"Reviewed full narration: {scene.narration}",
                    )
                    for _, scene in items
                ]
            finally:
                with self.lock:
                    self.active -= 1

    reviewer = Reviewer()
    pipeline = VideoProductionPipeline(image_reviewer=reviewer)
    request = pipeline.create_request(
        storyboard_file=storyboard_file,
        image_directory=image_directory,
        narration_result_file=alignment_file,
        audio_file=audio_file,
        output_directory=tmp_path / "output",
        enable_image_ai_qa=True,
    )

    assert pipeline._review_and_repair_images(request, tmp_path) == "PASS"
    metrics = load_project_qa(tmp_path).stages["image_semantic_qa"][-1].metrics
    assert reviewer.maximum_active == 2
    assert reviewer.calls_by_scene == {
        "scene_001": 1,
        "scene_002": 2,
        "scene_003": 1,
    }
    assert metrics["ai_batches"] == 3
    assert metrics["ai_retries"] == 1
    assert metrics["ai_reviewed_scenes"] == 3


def test_semantic_qa_only_reviews_scenes_with_contract_risk_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RITZZ_QA_IMAGE_WIDTH", "320")
    monkeypatch.setenv("RITZZ_QA_IMAGE_HEIGHT", "180")
    image_directory = create_images(tmp_path)
    audio_file = create_audio(tmp_path)
    storyboard_file = create_storyboard(tmp_path, audio_file)
    alignment_file = create_alignment(tmp_path)
    storyboard = StoryboardEngine.load_storyboard(storyboard_file)
    storyboard.scenes = [
        scene.model_copy(
            update={
                "visual_contract": SceneVisualContract(
                    scene_id=scene.scene_id,
                    purpose="EXPLAIN",
                    subject="A pirate",
                    action="Looks across the sea",
                    environment="A wooden ship at sea",
                    historical_context="Not established by the approved research.",
                    ambiguity_resolution="Show the described pirate and ship.",
                    semantic_review_reasons=(
                        ["historical accuracy needs verification"]
                        if scene.scene_id == "scene_002"
                        else []
                    ),
                )
            }
        )
        for scene in storyboard.scenes
    ]
    storyboard_file.write_text(
        storyboard.model_dump_json(indent=2),
        encoding="utf-8",
    )
    world = VisualWorldBible(
        topic=storyboard.topic,
        historical=False,
        time_period="Not established by the approved research.",
        geography="Not established by the approved research.",
        civilization_or_society="Not established by the approved research.",
        technology_level="Not established by the approved research.",
        built_environment="Not established by the approved research.",
        clothing="Not established by the approved research.",
        transportation="Not established by the approved research.",
        tools_and_weapons="Not established by the approved research.",
        containers_and_materials="Not established by the approved research.",
        architecture="Not established by the approved research.",
        natural_environment="The open sea.",
        social_context="Not established by the approved research.",
        visual_style="Simple 2D cartoon illustration.",
        technology_ceiling="Not established by the approved research.",
    )
    (tmp_path / "visual_world_bible.json").write_text(
        world.model_dump_json(indent=2),
        encoding="utf-8",
    )

    class Reviewer:
        def __init__(self):
            self.scene_ids: list[str] = []

        def review(self, image_path, scene, editorial_candidates=None):
            self.scene_ids.append(scene.scene_id)
            return SceneQAResult(
                scene_id=scene.scene_id,
                status="PASS",
                narration_image="PASS",
                narration_description="PASS",
                rationale="Targeted semantic risk review passed.",
            )

    reviewer = Reviewer()
    pipeline = VideoProductionPipeline(image_reviewer=reviewer)
    request = pipeline.create_request(
        storyboard_file=storyboard_file,
        image_directory=image_directory,
        narration_result_file=alignment_file,
        audio_file=audio_file,
        output_directory=tmp_path / "output",
        enable_image_ai_qa=True,
    )

    assert pipeline._review_and_repair_images(request, tmp_path) == "PASS"
    assert reviewer.scene_ids == ["scene_002"]
    metrics = load_project_qa(tmp_path).stages["image_semantic_qa"][-1].metrics
    assert metrics["ai_reviewed_scenes"] == 1


def test_no_editorial_policy_reviews_every_image_and_repairs_clear_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RITZZ_QA_IMAGE_WIDTH", "320")
    monkeypatch.setenv("RITZZ_QA_IMAGE_HEIGHT", "180")
    monkeypatch.setattr(
        "modules.video.image_asset_qa.detect_visible_text",
        lambda _path: (),
    )
    image_directory = create_images(tmp_path)
    audio_file = create_audio(tmp_path)
    storyboard_file = create_storyboard(tmp_path, audio_file)
    alignment_file = create_alignment(tmp_path)
    review_attempts: dict[str, int] = {}

    class Reviewer:
        def review(self, image_path, scene):
            review_attempts[scene.scene_id] = (
                review_attempts.get(scene.scene_id, 0) + 1
            )
            if (
                scene.scene_id == "scene_001"
                and review_attempts[scene.scene_id] == 1
            ):
                return SceneQAResult(
                    scene_id=scene.scene_id,
                    status="FAIL",
                    narration_image="PASS",
                    narration_description="PASS",
                    unwanted_text="FAIL",
                    rationale="The image contains an editorial word.",
                    correction_prompt="Remove the editorial word from the image.",
                    failure_category="UNWANTED_TEXT",
                )
            return SceneQAResult(
                scene_id=scene.scene_id,
                status="PASS",
                narration_image="PASS",
                narration_description="PASS",
                unwanted_text="PASS",
                rationale="No editorial lettering is visible.",
            )

    class ImageProvider:
        def __init__(self):
            self.generated_scenes: list[str] = []
            self.prompts: list[str] = []

        def generate(self, request):
            assert request.provider == "replicate"
            output = Path(request.output_directory) / f"{request.image_id}.png"
            shutil.copyfile(image_directory / f"{request.scene_id}.png", output)
            self.generated_scenes.append(request.scene_id)
            self.prompts.append(request.prompt)
            return ImageGenerationResult(
                image_id=request.image_id,
                scene_id=request.scene_id,
                provider="replicate",
                status="completed",
                file_path=str(output),
            )

    provider = ImageProvider()
    pipeline = VideoProductionPipeline(
        image_reviewer=Reviewer(),
        image_provider=provider,
        image_provider_name="replicate",
    )
    request = pipeline.create_request(
        storyboard_file=storyboard_file,
        image_directory=image_directory,
        narration_result_file=alignment_file,
        audio_file=audio_file,
        output_directory=tmp_path / "output",
        enable_image_ai_qa=True,
        require_no_editorial_text=True,
    )

    assert pipeline._review_and_repair_images(request, tmp_path) == "PASS"
    assert review_attempts == {
        "scene_001": 2,
        "scene_002": 1,
        "scene_003": 1,
    }
    assert provider.generated_scenes == ["scene_001"]
    assert "No words, letters, captions, labels, callouts, or typography" in (
        provider.prompts[0]
    )
    checks = load_project_qa(tmp_path).stages["image_semantic_qa"][-1].checks
    assert checks["scene_001.unwanted_text"] == "PASS"
    assert checks["scene_002.unwanted_text"] == "PASS"
    assert checks["scene_003.unwanted_text"] == "PASS"


@pytest.mark.parametrize(
    ("persists_after_repair", "expected_status"),
    [(False, "PASS"), (True, "FAIL")],
)
def test_local_ocr_text_finding_overrides_vision_pass_and_repairs_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    persists_after_repair: bool,
    expected_status: QAStatus,
) -> None:
    monkeypatch.setenv("RITZZ_QA_IMAGE_WIDTH", "320")
    monkeypatch.setenv("RITZZ_QA_IMAGE_HEIGHT", "180")
    image_directory = create_images(tmp_path)
    audio_file = create_audio(tmp_path)
    storyboard_file = create_storyboard(tmp_path, audio_file)
    alignment_file = create_alignment(tmp_path)
    scene_one_path = image_directory / "scene_001.png"
    scene_one_scans = 0

    def fake_ocr(image_path: str | Path) -> tuple[str, ...]:
        nonlocal scene_one_scans
        if Path(image_path) == scene_one_path:
            scene_one_scans += 1
            return (
                ("Ritzz.Hk",)
                if scene_one_scans == 1 or persists_after_repair
                else ()
            )
        return ()

    monkeypatch.setattr(
        "modules.video.image_asset_qa.detect_visible_text",
        fake_ocr,
    )

    class Reviewer:
        def review(self, image_path, scene):
            return SceneQAResult(
                scene_id=scene.scene_id,
                status="PASS",
                narration_image="PASS",
                narration_description="PASS",
                unwanted_text="PASS",
                rationale="The image appears to match its scene.",
            )

    class ImageProvider:
        def __init__(self) -> None:
            self.generated_scenes: list[str] = []

        def generate(self, request):
            output = Path(request.output_directory) / f"{request.image_id}.png"
            shutil.copyfile(scene_one_path, output)
            self.generated_scenes.append(request.scene_id)
            return ImageGenerationResult(
                image_id=request.image_id,
                scene_id=request.scene_id,
                provider="replicate",
                status="completed",
                file_path=str(output),
            )

    provider = ImageProvider()
    pipeline = VideoProductionPipeline(
        image_reviewer=Reviewer(),
        image_provider=provider,
        image_provider_name="replicate",
    )
    request = pipeline.create_request(
        storyboard_file=storyboard_file,
        image_directory=image_directory,
        narration_result_file=alignment_file,
        audio_file=audio_file,
        output_directory=tmp_path / "output",
        enable_image_ai_qa=True,
        require_no_editorial_text=True,
    )

    assert pipeline._review_and_repair_images(request, tmp_path) == expected_status
    expected_attempts = (
        pipeline.MAX_QA_REPAIR_ATTEMPTS if persists_after_repair else 1
    )
    assert provider.generated_scenes == ["scene_001"] * expected_attempts
    assert scene_one_scans == expected_attempts * 2
    checks = load_project_qa(tmp_path).stages["image_semantic_qa"][-1].checks
    assert checks["scene_001.unwanted_text"] == expected_status


def test_uncertain_text_is_preserved_for_review_without_regeneration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RITZZ_QA_IMAGE_WIDTH", "320")
    monkeypatch.setenv("RITZZ_QA_IMAGE_HEIGHT", "180")
    monkeypatch.setattr(
        "modules.video.image_asset_qa.detect_visible_text",
        lambda _path: (),
    )
    image_directory = create_images(tmp_path)
    audio_file = create_audio(tmp_path)
    storyboard_file = create_storyboard(tmp_path, audio_file)
    alignment_file = create_alignment(tmp_path)

    class Reviewer:
        def review(self, image_path, scene):
            return SceneQAResult(
                scene_id=scene.scene_id,
                status="REVIEW",
                narration_image="PASS",
                narration_description="PASS",
                unwanted_text="REVIEW",
                rationale="A mark may be text, but it is unclear.",
                correction_prompt="The mark may need review.",
            )

    class ImageProvider:
        def generate(self, request):
            pytest.fail("Uncertain text should be preserved for human review.")

    pipeline = VideoProductionPipeline(
        image_reviewer=Reviewer(),
        image_provider=ImageProvider(),
        image_provider_name="replicate",
    )
    request = pipeline.create_request(
        storyboard_file=storyboard_file,
        image_directory=image_directory,
        narration_result_file=alignment_file,
        audio_file=audio_file,
        output_directory=tmp_path / "output",
        enable_image_ai_qa=True,
        require_no_editorial_text=True,
    )

    assert pipeline._review_and_repair_images(request, tmp_path) == "REVIEW"
    checks = load_project_qa(tmp_path).stages["image_semantic_qa"][-1].checks
    assert checks["scene_001.unwanted_text"] == "REVIEW"


def test_image_ai_qa_preserves_uncertain_images_for_human_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RITZZ_QA_IMAGE_WIDTH", "320")
    monkeypatch.setenv("RITZZ_QA_IMAGE_HEIGHT", "180")
    image_directory = create_images(tmp_path)
    audio_file = create_audio(tmp_path)
    storyboard_file = create_storyboard(tmp_path, audio_file)
    alignment_file = create_alignment(tmp_path)

    class Reviewer:
        def review(self, image_path, scene, editorial_candidates=None):
            return SceneQAResult(
                scene_id=scene.scene_id,
                status="REVIEW",
                narration_image="REVIEW",
                narration_description="PASS",
                editorial_context="PASS",
                rationale="The visual relation is uncertain.",
            )

    class ImageProvider:
        def __init__(self):
            self.generated_scenes: list[str] = []

        def generate(self, request):
            output = Path(request.output_directory) / f"{request.image_id}.png"
            shutil.copyfile(image_directory / f"{request.scene_id}.png", output)
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

    assert status == "REVIEW"
    assert provider.generated_scenes == []
    qa_attempts = load_project_qa(tmp_path).stages["image_semantic_qa"]
    assert [attempt.status for attempt in qa_attempts] == ["REVIEW"]
    assert "no actionable image correction was supplied" in qa_attempts[0].findings[0]


@pytest.mark.parametrize(
    ("suggested_position", "failure_category"),
    [
        ("top_left", "EDITORIAL_OVER_FACE"),
        (None, "EDITORIAL_NO_SAFE_SPACE"),
    ],
)
def test_image_ai_qa_ignores_legacy_editorial_review_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suggested_position: str | None,
    failure_category: str,
) -> None:
    monkeypatch.setenv("RITZZ_QA_IMAGE_WIDTH", "320")
    monkeypatch.setenv("RITZZ_QA_IMAGE_HEIGHT", "180")
    image_directory = create_images(tmp_path)
    audio_file = create_audio(tmp_path)
    storyboard_file = create_storyboard(tmp_path, audio_file)
    alignment_file = create_alignment(tmp_path)
    storyboard = StoryboardEngine.load_storyboard(storyboard_file)
    storyboard.scenes[0].text_overlay = "ICONIC"
    storyboard.scenes[0].callout_not_warranted = False
    storyboard.scenes[0].callout_not_warranted_reason = None
    storyboard.scenes[0].callout_position = "top_right"
    StoryboardEngine.save_storyboard(storyboard, storyboard_file)
    review_attempts: dict[str, int] = {}

    class Reviewer:
        def review(self, image_path, scene, editorial_candidates=None):
            review_attempts[scene.scene_id] = (
                review_attempts.get(scene.scene_id, 0) + 1
            )
            if (
                scene.scene_id == "scene_001"
                and review_attempts[scene.scene_id] == 1
            ):
                return SceneQAResult(
                    scene_id=scene.scene_id,
                    status="PASS",
                    narration_image="PASS",
                    narration_description="PASS",
                    editorial_placement="FAIL",
                    editorial_obstruction="FAIL",
                    editorial_safe_space="FAIL",
                    suggested_editorial_position=suggested_position,
                    rationale="Legacy callout findings are not active QA criteria.",
                    correction_prompt="Do not use text-related repair guidance.",
                    failure_category=failure_category,
                )
            return SceneQAResult(
                scene_id=scene.scene_id,
                status="PASS",
                narration_image="PASS",
                narration_description="PASS",
                editorial_context="PASS",
                rationale="The image matches the scene.",
            )

    class ImageProvider:
        def __init__(self):
            self.generated_scenes: list[str] = []
            self.prompts: list[str] = []

        def generate(self, request):
            output = Path(request.output_directory) / f"{request.image_id}.png"
            shutil.copyfile(image_directory / f"{request.scene_id}.png", output)
            self.generated_scenes.append(request.scene_id)
            self.prompts.append(request.prompt)
            return ImageGenerationResult(
                image_id=request.image_id,
                scene_id=request.scene_id,
                provider="openai",
                status="completed",
                file_path=str(output),
            )

    provider = ImageProvider()
    pipeline = VideoProductionPipeline(
        image_reviewer=Reviewer(),
        image_provider=provider,
    )
    request = pipeline.create_request(
        storyboard_file=storyboard_file,
        image_directory=image_directory,
        narration_result_file=alignment_file,
        audio_file=audio_file,
        output_directory=tmp_path / "output",
        enable_image_ai_qa=True,
    )

    status = pipeline._review_and_repair_images(request, tmp_path)

    assert status == "PASS"
    assert provider.generated_scenes == []
    assert review_attempts == {
        "scene_001": 1,
        "scene_002": 1,
        "scene_003": 1,
    }
    assert provider.prompts == []
    repaired_storyboard = StoryboardEngine.load_storyboard(storyboard_file)
    assert repaired_storyboard.scenes[0].callout_position == "top_right"
    attempts = load_project_qa(tmp_path).stages["image_semantic_qa"]
    assert [attempt.status for attempt in attempts] == ["PASS"]
    assert not any("editorial" in name for name in attempts[0].checks)


def test_semantic_review_status_keeps_video_available_for_human_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_directory = create_images(tmp_path)
    audio_file = create_audio(tmp_path)
    storyboard_file = create_storyboard(tmp_path, audio_file)
    alignment_file = create_alignment(tmp_path)
    pipeline = VideoProductionPipeline()
    request = pipeline.create_request(
        storyboard_file=storyboard_file,
        image_directory=image_directory,
        narration_result_file=alignment_file,
        audio_file=audio_file,
        output_directory=tmp_path / "output",
        enable_image_ai_qa=True,
    )
    monkeypatch.setattr(
        pipeline,
        "_review_and_repair_images",
        lambda *_args: "REVIEW",
    )

    result = pipeline.run(request)

    assert result.status == "completed"
    assert result.technical_qa_status == "PASS"
    assert result.image_ai_qa_status == "REVIEW"
    assert result.output_video_file is not None
    assert Path(result.output_video_file).is_file()


def test_mandatory_no_editorial_text_review_blocks_video_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_directory = create_images(tmp_path)
    audio_file = create_audio(tmp_path)
    storyboard_file = create_storyboard(tmp_path, audio_file)
    alignment_file = create_alignment(tmp_path)
    pipeline = VideoProductionPipeline()
    request = pipeline.create_request(
        storyboard_file=storyboard_file,
        image_directory=image_directory,
        narration_result_file=alignment_file,
        audio_file=audio_file,
        output_directory=tmp_path / "output",
        enable_image_ai_qa=True,
        require_no_editorial_text=True,
    )
    monkeypatch.setattr(
        pipeline,
        "_review_and_repair_images",
        lambda *_args: "REVIEW",
    )

    result = pipeline.run(request)

    assert result.status == "failed"
    assert result.output_video_file is None
    assert result.error_message is not None
    assert "Mandatory no-editorial-text image QA did not PASS" in (
        result.error_message
    )


def test_semantic_failure_blocks_video_render_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_directory = create_images(tmp_path)
    audio_file = create_audio(tmp_path)
    storyboard_file = create_storyboard(tmp_path, audio_file)
    alignment_file = create_alignment(tmp_path)
    pipeline = VideoProductionPipeline()
    request = pipeline.create_request(
        storyboard_file=storyboard_file,
        image_directory=image_directory,
        narration_result_file=alignment_file,
        audio_file=audio_file,
        output_directory=tmp_path / "output",
        enable_image_ai_qa=True,
    )
    monkeypatch.setattr(
        pipeline,
        "_review_and_repair_images",
        lambda *_args: "FAIL",
    )

    result = pipeline.run(request)

    assert result.status == "failed"
    assert result.image_ai_qa_status == "FAIL"
    assert result.output_video_file is None


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

    def run_technical(self, storyboard, plan, audio, video, production_config=None):
        nonlocal technical_attempts
        technical_attempts += 1
        status = "REVIEW" if technical_attempts == 1 else "PASS"
        checks: dict[str, QAStatus] = {
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
            "audio_loudness": "REVIEW" if status == "REVIEW" else "PASS",
        }
        return TechnicalQAResult(
            status=status,
            checks=checks,
            issues=["Timeline drift needs synchronization."] if status == "REVIEW" else [],
            scene_count=len(plan.clips),
            audio_duration_seconds=12.0,
            video_duration_seconds=12.0,
            maximum_timeline_drift_seconds=1.0 if status == "REVIEW" else 0.0,
            integrated_lufs=-15.1 if status == "REVIEW" else -14.0,
            true_peak_dbtp=-0.7 if status == "REVIEW" else -1.1,
        )

    monkeypatch.setattr("modules.video.pipeline_engine.PilotVideoQA.run_technical", run_technical)
    pipeline = VideoProductionPipeline()
    original_render = pipeline.renderer.render
    peak_targets: list[float] = []

    def count_render(*args, **kwargs):
        nonlocal render_attempts
        render_attempts += 1
        peak_targets.append(
            pipeline.renderer.audio_filter_true_peak_target_dbtp
        )
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
    assert peak_targets == [-2.0, pytest.approx(-2.7)]
    qa_report = load_project_qa(tmp_path)
    assert [item.status for item in qa_report.stages["technical_qa"]] == [
        "REVIEW",
        "PASS",
    ]
    assert qa_report.stages["technical_qa_repair"][-1].status == "PASS"
    assert "loudnorm true-peak target -2.0 -> -2.7 dBTP" in (
        qa_report.stages["technical_qa_repair"][0].recommendations[0]
    )
    pipeline_state = json.loads(
        (tmp_path / "output" / "pipeline_state.json").read_text(encoding="utf-8")
    )
    assert pipeline_state["stages"]["render"]["status"] == "completed"
    assert pipeline_state["stages"]["technical_qa"]["status"] == "completed"


def test_pipeline_leaves_render_incomplete_when_technical_qa_never_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_directory = create_images(tmp_path)
    audio_file = create_audio(tmp_path)
    storyboard_file = create_storyboard(tmp_path, audio_file)
    alignment_file = create_alignment(tmp_path)
    qa_attempts = 0
    render_attempts = 0

    def run_technical(self, storyboard, plan, audio, video, production_config=None):
        nonlocal qa_attempts
        qa_attempts += 1
        checks: dict[str, QAStatus] = {
            "images": "PASS",
            "audio": "PASS",
            "scene_order": "PASS",
            "timestamps_monotonic": "PASS",
            "no_gaps_or_overlaps": "PASS",
            "scene_durations": "PASS",
            "duration_consistency": "PASS",
            "video": "PASS",
            "timestamp_coverage": "PASS",
            "timeline_drift": "PASS",
            "audio_loudness": "REVIEW",
        }
        return TechnicalQAResult(
            status="REVIEW",
            checks=checks,
            issues=["Audio loudness remains outside target."],
            scene_count=len(plan.clips),
            audio_duration_seconds=12.0,
            video_duration_seconds=12.0,
            maximum_timeline_drift_seconds=0.0,
        )

    monkeypatch.setattr(
        "modules.video.pipeline_engine.PilotVideoQA.run_technical",
        run_technical,
    )
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
    pipeline_state = json.loads(
        (tmp_path / "output" / "pipeline_state.json").read_text(encoding="utf-8")
    )
    qa_report = load_project_qa(tmp_path)

    assert result.status == "failed"
    assert result.technical_qa_status == "REVIEW"
    assert qa_attempts == VideoProductionPipeline.MAX_QA_REPAIR_ATTEMPTS
    assert render_attempts == VideoProductionPipeline.MAX_QA_REPAIR_ATTEMPTS
    assert pipeline_state["stages"]["render"]["status"] == "failed"
    assert pipeline_state["stages"]["technical_qa"]["status"] == "failed"
    assert len(qa_report.stages["technical_qa"]) == VideoProductionPipeline.MAX_QA_REPAIR_ATTEMPTS


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