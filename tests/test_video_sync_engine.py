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
from modules.video.sync_engine import (
    VideoSynchronizationEngine,
)
from modules.video.sync_models import (
    NarrationAlignment,
    VideoSynchronizationRequest,
    VideoSynchronizationResult,
)


def create_storyboard() -> Storyboard:
    scenes = [
        StoryboardScene(
            scene_id="scene_001",
            section_id="s1",
            start_seconds=0.0,
            duration_seconds=5.0,
            narration=(
                "The pirate looks across the sea."
            ),
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
            narration=(
                "He suddenly notices something."
            ),
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
            narration=(
                "The mystery begins."
            ),
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
                duration_seconds=5.0,
                status="ready",
            ),
            VideoClip(
                scene_id="scene_002",
                image_path="scene_002.png",
                start_seconds=5.0,
                duration_seconds=5.0,
                status="ready",
            ),
            VideoClip(
                scene_id="scene_003",
                image_path="scene_003.png",
                start_seconds=10.0,
                duration_seconds=5.0,
                status="ready",
            ),
        ],
        total_duration_seconds=15.0,
        audio_path="narration.mp3",
    )


def create_alignment() -> NarrationAlignment:
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

        current += 0.1

        ends.append(
            round(current, 3)
        )

    return NarrationAlignment(
        characters=characters,
        character_start_times_seconds=starts,
        character_end_times_seconds=ends,
        audio_duration_seconds=32.5,
    )


def write_alignment_file(
    path: Path,
    alignment: NarrationAlignment,
) -> None:
    data = {
        "duration_seconds": (
            alignment.audio_duration_seconds
        ),
        "alignment": {
            "characters": alignment.characters,
            "character_start_times_seconds": (
                alignment.character_start_times_seconds
            ),
            "character_end_times_seconds": (
                alignment.character_end_times_seconds
            ),
        },
    }

    path.write_text(
        json.dumps(data),
        encoding="utf-8",
    )


def test_load_narration_alignment(
    tmp_path: Path,
) -> None:
    alignment = create_alignment()

    result_file = (
        tmp_path / "narration_result.json"
    )

    write_alignment_file(
        result_file,
        alignment,
    )

    engine = VideoSynchronizationEngine()

    loaded = engine.load_narration_alignment(
        result_file
    )

    assert loaded == alignment


def test_actual_audio_duration_takes_precedence_over_alignment_estimate(
    tmp_path: Path,
) -> None:
    alignment = create_alignment()
    result_file = tmp_path / "narration_result.json"
    write_alignment_file(result_file, alignment)
    data = json.loads(result_file.read_text(encoding="utf-8"))
    data["duration_seconds"] = 31.7
    data["actual_duration_seconds"] = 32.5
    result_file.write_text(json.dumps(data), encoding="utf-8")

    loaded = VideoSynchronizationEngine.load_narration_alignment(result_file)

    assert loaded.audio_duration_seconds == 32.5


def test_rejects_audio_below_recorded_minimum(tmp_path: Path) -> None:
    alignment = create_alignment()
    result_file = tmp_path / "short_result.json"
    write_alignment_file(result_file, alignment)
    data = json.loads(result_file.read_text(encoding="utf-8"))
    data["actual_duration_seconds"] = 31.0
    data["minimum_duration_seconds"] = 32.0
    result_file.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="shorter than its required minimum"):
        VideoSynchronizationEngine.load_narration_alignment(result_file)


def test_mismatched_alignment_lengths_fail() -> None:
    with pytest.raises(
        ValueError,
        match="start timestamp count",
    ):
        VideoSynchronizationEngine._validate_alignment(
            NarrationAlignment(
                characters=[
                    "a",
                    "b",
                ],
                character_start_times_seconds=[
                    0.0,
                ],
                character_end_times_seconds=[
                    0.1,
                    0.2,
                ],
                audio_duration_seconds=1.0,
            )
        )


def test_synchronize_plan_uses_actual_audio_timing() -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()
    alignment = create_alignment()

    engine = VideoSynchronizationEngine()

    plan = engine.synchronize_plan(
        storyboard=storyboard,
        assembly_plan=assembly_plan,
        alignment=alignment,
    )

    assert plan.total_duration_seconds == 32.5

    assert len(plan.clips) == 3

    # Actual narration timing is the source of truth.
    assert plan.clips[0].start_seconds == 0.0

    assert plan.clips[1].start_seconds == pytest.approx(
        3.3
    )

    assert plan.clips[2].start_seconds == pytest.approx(
        6.4
    )

    assert (
        plan.clips[-1].start_seconds
        + plan.clips[-1].duration_seconds
    ) == pytest.approx(
        alignment.audio_duration_seconds
    )


def test_synchronized_clips_are_continuous() -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()
    alignment = create_alignment()

    engine = VideoSynchronizationEngine()

    plan = engine.synchronize_plan(
        storyboard,
        assembly_plan,
        alignment,
    )

    for index in range(
        1,
        len(plan.clips),
    ):
        previous = plan.clips[
            index - 1
        ]

        current = plan.clips[
            index
        ]

        assert current.start_seconds == pytest.approx(
            previous.start_seconds
            + previous.duration_seconds
        )


def test_plan_preserves_image_paths() -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()
    alignment = create_alignment()

    engine = VideoSynchronizationEngine()

    plan = engine.synchronize_plan(
        storyboard,
        assembly_plan,
        alignment,
    )

    assert [
        clip.image_path
        for clip in plan.clips
    ] == [
        "scene_001.png",
        "scene_002.png",
        "scene_003.png",
    ]


def test_plan_preserves_video_settings() -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()
    alignment = create_alignment()

    engine = VideoSynchronizationEngine()

    plan = engine.synchronize_plan(
        storyboard,
        assembly_plan,
        alignment,
    )

    assert plan.width == 1536
    assert plan.height == 864
    assert plan.fps == 30


def test_plan_preserves_audio_path() -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()
    alignment = create_alignment()

    engine = VideoSynchronizationEngine()

    plan = engine.synchronize_plan(
        storyboard,
        assembly_plan,
        alignment,
    )

    assert plan.audio_path == (
        "narration.mp3"
    )


def test_topic_mismatch_fails() -> None:
    storyboard = create_storyboard()

    assembly_plan = create_assembly_plan().model_copy(
        update={
            "topic": "Different Topic"
        }
    )

    alignment = create_alignment()

    engine = VideoSynchronizationEngine()

    with pytest.raises(
        ValueError,
        match="topic",
    ):
        engine.synchronize_plan(
            storyboard,
            assembly_plan,
            alignment,
        )


def test_empty_storyboard_fails() -> None:
    storyboard = Storyboard(
        topic="Empty",
        target_duration_seconds=1,
        scenes=[],
        total_scene_duration_seconds=0.0,
        target_scene_duration_seconds=5.0,
    )

    assembly_plan = VideoAssemblyPlan(
        topic="Empty",
        clips=[
            VideoClip(
                scene_id="scene_001",
                image_path="scene_001.png",
                start_seconds=0.0,
                duration_seconds=1.0,
                status="ready",
            )
        ],
        total_duration_seconds=1.0,
        audio_path="narration.mp3",
    )

    alignment = create_alignment()

    engine = VideoSynchronizationEngine()

    with pytest.raises(
        ValueError,
        match="empty storyboard",
    ):
        engine.synchronize_plan(
            storyboard,
            assembly_plan,
            alignment,
        )


def test_unmatched_scene_narration_fails() -> None:
    storyboard = create_storyboard()

    storyboard = storyboard.model_copy(
        update={
            "scenes": [
                storyboard.scenes[0].model_copy(
                    update={
                        "narration": (
                            "This narration does not exist."
                        )
                    }
                ),
                *storyboard.scenes[1:],
            ]
        }
    )

    alignment = create_alignment()

    engine = VideoSynchronizationEngine()

    with pytest.raises(
        ValueError,
        match="Could not match storyboard narration",
    ):
        engine._match_scene_narration(
            storyboard,
            alignment,
        )


def test_audio_duration_is_final_timeline_end() -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()
    alignment = create_alignment()

    engine = VideoSynchronizationEngine()

    plan = engine.synchronize_plan(
        storyboard,
        assembly_plan,
        alignment,
    )

    final_clip = plan.clips[-1]

    final_end = (
        final_clip.start_seconds
        + final_clip.duration_seconds
    )

    assert final_end == pytest.approx(
        alignment.audio_duration_seconds
    )


def test_create_request(
    tmp_path: Path,
) -> None:
    engine = VideoSynchronizationEngine()

    request = engine.create_request(
        tmp_path / "storyboard.json",
        tmp_path / "video_plan.json",
        tmp_path / "narration_result.json",
    )

    assert isinstance(
        request,
        VideoSynchronizationRequest,
    )

    assert request.storyboard_file == str(
        tmp_path / "storyboard.json"
    )

    assert request.assembly_plan_file == str(
        tmp_path / "video_plan.json"
    )

    assert request.narration_result_file == str(
        tmp_path / "narration_result.json"
    )


def test_run_saves_synchronized_plan(
    tmp_path: Path,
) -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()
    alignment = create_alignment()

    storyboard_file = (
        tmp_path / "storyboard.json"
    )

    assembly_plan_file = (
        tmp_path / "video_plan.json"
    )

    narration_result_file = (
        tmp_path / "narration_result.json"
    )

    output_plan_file = (
        tmp_path / "synced_video_plan.json"
    )

    storyboard_file.write_text(
        json.dumps(
            storyboard.model_dump()
        ),
        encoding="utf-8",
    )

    VideoAssemblyEngine.save_plan(
        assembly_plan,
        assembly_plan_file,
    )

    write_alignment_file(
        narration_result_file,
        alignment,
    )

    engine = VideoSynchronizationEngine()

    request = engine.create_request(
        storyboard_file,
        assembly_plan_file,
        narration_result_file,
    )

    result = engine.run(
        request,
        output_plan_file,
    )

    assert isinstance(
        result,
        VideoSynchronizationResult,
    )

    assert result.status == "completed"

    assert result.scene_count == 3

    assert result.plan_file == str(
        output_plan_file
    )

    assert output_plan_file.exists()


def test_saved_synchronized_plan_is_valid_json(
    tmp_path: Path,
) -> None:
    storyboard = create_storyboard()
    assembly_plan = create_assembly_plan()
    alignment = create_alignment()

    storyboard_file = (
        tmp_path / "storyboard.json"
    )

    assembly_plan_file = (
        tmp_path / "video_plan.json"
    )

    narration_result_file = (
        tmp_path / "narration_result.json"
    )

    output_plan_file = (
        tmp_path / "synced_video_plan.json"
    )

    storyboard_file.write_text(
        json.dumps(
            storyboard.model_dump()
        ),
        encoding="utf-8",
    )

    VideoAssemblyEngine.save_plan(
        assembly_plan,
        assembly_plan_file,
    )

    write_alignment_file(
        narration_result_file,
        alignment,
    )

    engine = VideoSynchronizationEngine()

    request = engine.create_request(
        storyboard_file,
        assembly_plan_file,
        narration_result_file,
    )

    result = engine.run(
        request,
        output_plan_file,
    )

    assert result.status == "completed"

    data = json.loads(
        output_plan_file.read_text(
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

    assert data[
        "total_duration_seconds"
    ] == pytest.approx(
        32.5
    )
