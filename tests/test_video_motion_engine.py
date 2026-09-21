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
    VideoClip,
)

from modules.video.motion_engine import (
    VideoMotionEngine,
)

from modules.video.motion_models import (
    MotionInstruction,
    VideoMotionPlan,
    VideoMotionRequest,
    VideoMotionResult,
)


def create_storyboard() -> Storyboard:
    scenes = [
        StoryboardScene.model_validate(
            {
                "scene_id": "scene_001",
                "section_id": "s1",
                "start_seconds": 0.0,
                "duration_seconds": 3.3,
                "narration": (
                    "The pirate looks across the sea."
                ),
                "visual_description": (
                    "A pirate standing on a wooden ship."
                ),
                "camera_motion": "slow_zoom_in",
                "image_prompt": (
                    "Simple pirate illustration."
                ),
            }
        ),
        StoryboardScene.model_validate(
            {
                "scene_id": "scene_002",
                "section_id": "s1",
                "start_seconds": 3.3,
                "duration_seconds": 3.1,
                "narration": (
                    "He suddenly notices something."
                ),
                "visual_description": (
                    "The pirate looks surprised."
                ),
                "camera_motion": "pan_right",
                "image_prompt": (
                    "Simple surprised pirate illustration."
                ),
            }
        ),
        StoryboardScene.model_validate(
            {
                "scene_id": "scene_003",
                "section_id": "s1",
                "start_seconds": 6.4,
                "duration_seconds": 26.1,
                "narration": (
                    "The mystery begins."
                ),
                "visual_description": (
                    "The pirate investigates a mystery."
                ),
                "camera_motion": "static",
                "image_prompt": (
                    "Simple pirate mystery illustration."
                ),
            }
        ),
    ]

    return Storyboard(
        topic="Why Do Pirates Wear Eye Patches?",
        target_duration_seconds=33,
        scenes=scenes,
        total_scene_duration_seconds=32.5,
        target_scene_duration_seconds=5.0,
    )


def create_assembly_plan() -> VideoAssemblyPlan:
    return VideoAssemblyPlan(
        topic="Why Do Pirates Wear Eye Patches?",
        width=1536,
        height=864,
        fps=30,
        clips=[
            VideoClip(
                scene_id="scene_001",
                image_path="scene_001.png",
                start_seconds=0.0,
                duration_seconds=3.3,
                status="ready",
            ),
            VideoClip(
                scene_id="scene_002",
                image_path="scene_002.png",
                start_seconds=3.3,
                duration_seconds=3.1,
                status="ready",
            ),
            VideoClip(
                scene_id="scene_003",
                image_path="scene_003.png",
                start_seconds=6.4,
                duration_seconds=26.1,
                status="ready",
            ),
        ],
        total_duration_seconds=32.5,
        audio_path="narration.mp3",
    )


def test_create_motion_plan() -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()

    engine = VideoMotionEngine()

    plan = engine.create_plan(
        storyboard,
        assembly_plan,
    )

    assert isinstance(
        plan,
        VideoMotionPlan,
    )

    assert plan.topic == (
        "Why Do Pirates Wear Eye Patches?"
    )

    assert len(
        plan.instructions
    ) == 3

    assert (
        plan.total_duration_seconds
        == 32.5
    )


def test_motion_order_matches_storyboard() -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()

    engine = VideoMotionEngine()

    plan = engine.create_plan(
        storyboard,
        assembly_plan,
    )

    assert [
        instruction.scene_id
        for instruction in plan.instructions
    ] == [
        "scene_001",
        "scene_002",
        "scene_003",
    ]


def test_zoom_in_instruction() -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()

    engine = VideoMotionEngine()

    plan = engine.create_plan(
        storyboard,
        assembly_plan,
    )

    instruction = plan.instructions[0]

    assert isinstance(
        instruction,
        MotionInstruction,
    )

    assert instruction.motion == (
        "slow_zoom_in"
    )

    assert instruction.zoom_start == 1.0

    assert instruction.zoom_end == pytest.approx(
        1.10
    )

    assert instruction.position_x_start == 0.5
    assert instruction.position_x_end == 0.5
    assert instruction.position_y_start == 0.5
    assert instruction.position_y_end == 0.5


def test_pan_right_instruction() -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()

    engine = VideoMotionEngine()

    plan = engine.create_plan(
        storyboard,
        assembly_plan,
    )

    instruction = plan.instructions[1]

    assert instruction.motion == (
        "pan_right"
    )

    assert instruction.zoom_start == pytest.approx(
        1.10
    )

    assert instruction.zoom_end == pytest.approx(
        1.10
    )

    assert instruction.position_x_start == pytest.approx(
        0.40
    )

    assert instruction.position_x_end == pytest.approx(
        0.60
    )


def test_static_instruction() -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()

    engine = VideoMotionEngine()

    plan = engine.create_plan(
        storyboard,
        assembly_plan,
    )

    instruction = plan.instructions[2]

    assert instruction.motion == (
        "static"
    )

    assert instruction.zoom_start == 1.0
    assert instruction.zoom_end == 1.0

    assert instruction.position_x_start == 0.5
    assert instruction.position_x_end == 0.5
    assert instruction.position_y_start == 0.5
    assert instruction.position_y_end == 0.5


def test_motion_timing_matches_assembly() -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()

    engine = VideoMotionEngine()

    plan = engine.create_plan(
        storyboard,
        assembly_plan,
    )

    for instruction, clip in zip(
        plan.instructions,
        assembly_plan.clips,
    ):
        assert (
            instruction.start_seconds
            == pytest.approx(
                clip.start_seconds
            )
        )

        assert (
            instruction.duration_seconds
            == pytest.approx(
                clip.duration_seconds
            )
        )


def test_motion_timeline_is_continuous() -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()

    engine = VideoMotionEngine()

    plan = engine.create_plan(
        storyboard,
        assembly_plan,
    )

    previous_end = 0.0

    for instruction in plan.instructions:
        assert instruction.start_seconds == pytest.approx(
            previous_end
        )

        previous_end = (
            instruction.start_seconds
            + instruction.duration_seconds
        )

    assert previous_end == pytest.approx(
        plan.total_duration_seconds
    )


def test_motion_settings_preserved() -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()

    engine = VideoMotionEngine()

    plan = engine.create_plan(
        storyboard,
        assembly_plan,
    )

    assert plan.width == 1536
    assert plan.height == 864
    assert plan.fps == 30


def test_save_and_load_motion_plan(
    tmp_path: Path,
) -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()

    engine = VideoMotionEngine()

    plan = engine.create_plan(
        storyboard,
        assembly_plan,
    )

    plan_file = (
        tmp_path / "motion_plan.json"
    )

    saved = engine.save_plan(
        plan,
        plan_file,
    )

    assert saved.exists()

    loaded = engine.load_plan(
        plan_file
    )

    assert loaded == plan


def test_motion_plan_json_is_valid(
    tmp_path: Path,
) -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()

    engine = VideoMotionEngine()

    plan = engine.create_plan(
        storyboard,
        assembly_plan,
    )

    plan_file = (
        tmp_path / "motion_plan.json"
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
        data["instructions"]
    ) == 3


def test_create_request(
    tmp_path: Path,
) -> None:
    engine = VideoMotionEngine()

    request = engine.create_request(
        tmp_path / "storyboard.json",
        tmp_path / "video_plan.json",
    )

    assert isinstance(
        request,
        VideoMotionRequest,
    )

    assert request.storyboard_file == str(
        tmp_path / "storyboard.json"
    )

    assert request.assembly_plan_file == str(
        tmp_path / "video_plan.json"
    )


def test_empty_storyboard_fails() -> None:
    storyboard = Storyboard(
        topic="Empty",
        target_duration_seconds=1,
        scenes=[],
        total_scene_duration_seconds=0.0,
        target_scene_duration_seconds=5.0,
    )

    assembly_plan = create_assembly_plan()

    engine = VideoMotionEngine()

    with pytest.raises(
        ValueError,
        match="empty storyboard",
    ):
        engine.create_plan(
            storyboard,
            assembly_plan,
        )


def test_topic_mismatch_fails() -> None:
    storyboard = create_storyboard()

    assembly_plan = create_assembly_plan().model_copy(
        update={
            "topic": "Different Topic"
        }
    )

    engine = VideoMotionEngine()

    with pytest.raises(
        ValueError,
        match="topic",
    ):
        engine.create_plan(
            storyboard,
            assembly_plan,
        )


def test_result_model() -> None:
    result = VideoMotionResult(
        status="completed",
        plan_file="motion_plan.json",
        scene_count=3,
        total_duration_seconds=32.5,
    )

    assert result.status == "completed"
    assert result.scene_count == 3
    assert result.total_duration_seconds == 32.5