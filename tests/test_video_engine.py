import json
from pathlib import Path

import pytest

from modules.storyboard.models import (
    Storyboard,
    StoryboardScene,
)
from modules.video.engine import (
    VideoAssemblyEngine,
)
from modules.video.models import (
    VideoAssemblyPlan,
)


def create_storyboard() -> Storyboard:
    scenes = [
        StoryboardScene(
            scene_id="scene_001",
            section_id="s1",
            start_seconds=0.0,
            duration_seconds=5.0,
            narration="The pirate looks across the sea.",
            visual_description=(
                "A pirate standing on a wooden ship."
            ),
            image_prompt=(
                "Simple pirate illustration."
            ),
        ),
        StoryboardScene(
            scene_id="scene_002",
            section_id="s1",
            start_seconds=5.0,
            duration_seconds=5.0,
            narration="He suddenly notices something.",
            visual_description=(
                "The pirate looks surprised."
            ),
            image_prompt=(
                "Simple surprised pirate illustration."
            ),
        ),
        StoryboardScene(
            scene_id="scene_003",
            section_id="s1",
            start_seconds=10.0,
            duration_seconds=5.0,
            narration="The mystery begins.",
            visual_description=(
                "The pirate investigates a mystery."
            ),
            image_prompt=(
                "Simple pirate mystery illustration."
            ),
        ),
    ]

    return Storyboard(
        topic="Why Do Pirates Wear Eye Patches?",
        target_duration_seconds=15,
        scenes=scenes,
        total_scene_duration_seconds=15.0,
        target_scene_duration_seconds=5.0,
    )


def create_images(
    image_directory: Path,
    storyboard: Storyboard,
) -> None:
    image_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    for scene in storyboard.scenes:
        image_file = (
            image_directory
            / f"{scene.scene_id}.png"
        )

        image_file.write_bytes(
            b"fake-image-data"
        )


def test_create_plan(
    tmp_path: Path,
) -> None:
    storyboard = create_storyboard()

    image_directory = (
        tmp_path / "images"
    )

    create_images(
        image_directory,
        storyboard,
    )

    engine = VideoAssemblyEngine()

    plan = engine.create_plan(
        storyboard,
        image_directory,
    )

    assert isinstance(
        plan,
        VideoAssemblyPlan,
    )

    assert plan.topic == (
        "Why Do Pirates Wear Eye Patches?"
    )

    assert plan.width == 1536
    assert plan.height == 864
    assert plan.fps == 30
    assert len(plan.clips) == 3
    assert plan.total_duration_seconds == 15.0


def test_clip_order_matches_storyboard(
    tmp_path: Path,
) -> None:
    storyboard = create_storyboard()

    image_directory = (
        tmp_path / "images"
    )

    create_images(
        image_directory,
        storyboard,
    )

    engine = VideoAssemblyEngine()

    plan = engine.create_plan(
        storyboard,
        image_directory,
    )

    scene_ids = [
        clip.scene_id
        for clip in plan.clips
    ]

    assert scene_ids == [
        "scene_001",
        "scene_002",
        "scene_003",
    ]


def test_clip_timing_matches_storyboard(
    tmp_path: Path,
) -> None:
    storyboard = create_storyboard()

    image_directory = (
        tmp_path / "images"
    )

    create_images(
        image_directory,
        storyboard,
    )

    engine = VideoAssemblyEngine()

    plan = engine.create_plan(
        storyboard,
        image_directory,
    )

    assert plan.clips[0].start_seconds == 0.0
    assert plan.clips[0].duration_seconds == 5.0

    assert plan.clips[1].start_seconds == 5.0
    assert plan.clips[1].duration_seconds == 5.0

    assert plan.clips[2].start_seconds == 10.0
    assert plan.clips[2].duration_seconds == 5.0


def test_missing_image_fails(
    tmp_path: Path,
) -> None:
    storyboard = create_storyboard()

    image_directory = (
        tmp_path / "images"
    )

    image_directory.mkdir()

    engine = VideoAssemblyEngine()

    with pytest.raises(
        ValueError,
        match="scene_001",
    ):
        engine.create_plan(
            storyboard,
            image_directory,
        )


def test_empty_image_fails(
    tmp_path: Path,
) -> None:
    storyboard = create_storyboard()

    image_directory = (
        tmp_path / "images"
    )

    create_images(
        image_directory,
        storyboard,
    )

    empty_file = (
        image_directory
        / "scene_002.png"
    )

    empty_file.write_bytes(
        b""
    )

    engine = VideoAssemblyEngine()

    with pytest.raises(
        ValueError,
        match="scene_002",
    ):
        engine.create_plan(
            storyboard,
            image_directory,
        )


def test_audio_file_is_validated(
    tmp_path: Path,
) -> None:
    storyboard = create_storyboard()

    image_directory = (
        tmp_path / "images"
    )

    create_images(
        image_directory,
        storyboard,
    )

    audio_file = (
        tmp_path / "narration.mp3"
    )

    audio_file.write_bytes(
        b"fake-audio-data"
    )

    engine = VideoAssemblyEngine()

    plan = engine.create_plan(
        storyboard,
        image_directory,
        audio_file,
    )

    assert plan.audio_path == str(
        audio_file
    )


def test_missing_audio_fails(
    tmp_path: Path,
) -> None:
    storyboard = create_storyboard()

    image_directory = (
        tmp_path / "images"
    )

    create_images(
        image_directory,
        storyboard,
    )

    engine = VideoAssemblyEngine()

    with pytest.raises(
        FileNotFoundError,
    ):
        engine.create_plan(
            storyboard,
            image_directory,
            tmp_path
            / "missing.mp3",
        )


def test_save_and_load_plan(
    tmp_path: Path,
) -> None:
    storyboard = create_storyboard()

    image_directory = (
        tmp_path / "images"
    )

    create_images(
        image_directory,
        storyboard,
    )

    engine = VideoAssemblyEngine()

    plan = engine.create_plan(
        storyboard,
        image_directory,
    )

    plan_file = (
        tmp_path
        / "video_plan.json"
    )

    saved_path = engine.save_plan(
        plan,
        plan_file,
    )

    assert saved_path.exists()

    loaded_plan = engine.load_plan(
        plan_file
    )

    assert loaded_plan == plan


def test_saved_plan_is_valid_json(
    tmp_path: Path,
) -> None:
    storyboard = create_storyboard()

    image_directory = (
        tmp_path / "images"
    )

    create_images(
        image_directory,
        storyboard,
    )

    engine = VideoAssemblyEngine()

    plan = engine.create_plan(
        storyboard,
        image_directory,
    )

    plan_file = (
        tmp_path
        / "video_plan.json"
    )

    engine.save_plan(
        plan,
        plan_file,
    )

    data = json.loads(
        plan_file.read_text(
            encoding="utf-8"
        )
    )

    assert isinstance(
        data,
        dict,
    )

    assert data["topic"] == (
        "Why Do Pirates Wear Eye Patches?"
    )

    assert len(
        data["clips"]
    ) == 3


def test_create_request(
    tmp_path: Path,
) -> None:
    storyboard_file = (
        tmp_path / "storyboard.json"
    )

    image_directory = (
        tmp_path / "images"
    )

    engine = VideoAssemblyEngine()

    request = engine.create_request(
        storyboard_file,
        image_directory,
    )

    assert request.storyboard_file == str(
        storyboard_file
    )

    assert request.image_directory == str(
        image_directory
    )

    assert request.width == 1536
    assert request.height == 864
    assert request.fps == 30


def test_custom_video_settings(
    tmp_path: Path,
) -> None:
    storyboard = create_storyboard()

    image_directory = (
        tmp_path / "images"
    )

    create_images(
        image_directory,
        storyboard,
    )

    engine = VideoAssemblyEngine(
        width=1920,
        height=1080,
        fps=24,
    )

    plan = engine.create_plan(
        storyboard,
        image_directory,
    )

    assert plan.width == 1920
    assert plan.height == 1080
    assert plan.fps == 24


def test_invalid_engine_settings() -> None:
    with pytest.raises(
        ValueError,
    ):
        VideoAssemblyEngine(
            width=0
        )

    with pytest.raises(
        ValueError,
    ):
        VideoAssemblyEngine(
            height=0
        )

    with pytest.raises(
        ValueError,
    ):
        VideoAssemblyEngine(
            fps=0
        )