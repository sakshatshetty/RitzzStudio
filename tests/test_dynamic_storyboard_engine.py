import pytest

from modules.storyboard.dynamic_engine import (
    DynamicStoryboardEngine,
)
from modules.storyboard.models import (
    Storyboard,
    StoryboardScene,
)


def create_source_storyboard() -> Storyboard:
    scenes = [
        StoryboardScene(
            scene_id="scene_001",
            section_id="s1",
            start_seconds=0.0,
            duration_seconds=5.0,
            narration=(
                "The pirate looks across the sea "
                "before he notices something."
            ),
            visual_description=(
                "A pirate standing on a wooden ship."
            ),
            character_action=(
                "The pirate looks across the sea."
            ),
            background="Simple ocean background.",
            props=["ship wheel"],
            camera_motion="static",
            transition="cut",
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
                "The real reason is surprisingly "
                "simple and practical."
            ),
            visual_description=(
                "The pirate considers the real reason."
            ),
            character_action=(
                "The pirate thinks."
            ),
            background="Simple ship deck.",
            props=["eye patch"],
            camera_motion="static",
            transition="cut",
            image_prompt=(
                "Simple pirate mystery illustration."
            ),
        ),
        StoryboardScene(
            scene_id="scene_003",
            section_id="s2",
            start_seconds=10.0,
            duration_seconds=5.0,
            narration=(
                "Many people imagine that this mystery "
                "goes back thousands of years."
            ),
            visual_description=(
                "A pirate thinking about the past."
            ),
            character_action=(
                "The pirate looks thoughtful."
            ),
            background="Simple historical background.",
            props=["old map"],
            camera_motion="static",
            transition="cut",
            image_prompt=(
                "Simple historical pirate illustration."
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


def test_dynamic_storyboard_creates_scenes() -> None:
    engine = DynamicStoryboardEngine()

    source = create_source_storyboard()

    result = engine.create_pilot_storyboard(
        source,
        target_duration_seconds=12,
    )

    assert result.scenes

    assert len(result.scenes) > (
        len(source.scenes)
    )


def test_scene_duration_between_one_and_three_seconds() -> None:
    engine = DynamicStoryboardEngine()

    source = create_source_storyboard()

    result = engine.create_pilot_storyboard(
        source,
        target_duration_seconds=12,
    )

    for scene in result.scenes:
        assert 1.0 <= scene.duration_seconds <= 3.0


def test_scene_timeline_is_continuous() -> None:
    engine = DynamicStoryboardEngine()

    source = create_source_storyboard()

    result = engine.create_pilot_storyboard(
        source,
        target_duration_seconds=12,
    )

    expected_start = 0.0

    for scene in result.scenes:
        assert scene.start_seconds == pytest.approx(
            expected_start
        )

        expected_start += (
            scene.duration_seconds
        )

    assert result.total_scene_duration_seconds == pytest.approx(
        expected_start
    )


def test_scene_ids_are_sequential() -> None:
    engine = DynamicStoryboardEngine()

    source = create_source_storyboard()

    result = engine.create_pilot_storyboard(
        source,
        target_duration_seconds=12,
    )

    assert [
        scene.scene_id
        for scene in result.scenes
    ] == [
        f"scene_{index:03d}"
        for index in range(
            1,
            len(result.scenes) + 1,
        )
    ]


def test_camera_motion_is_removed() -> None:
    engine = DynamicStoryboardEngine()

    source = create_source_storyboard()

    result = engine.create_pilot_storyboard(
        source,
        target_duration_seconds=12,
    )

    assert all(
        scene.camera_motion == "static"
        for scene in result.scenes
    )


def test_transitions_are_hard_cuts() -> None:
    engine = DynamicStoryboardEngine()

    source = create_source_storyboard()

    result = engine.create_pilot_storyboard(
        source,
        target_duration_seconds=12,
    )

    assert all(
        scene.transition == "cut"
        for scene in result.scenes
    )


def test_editorial_text_is_mandatory_every_three_to_four_scenes() -> None:
    engine = DynamicStoryboardEngine()

    source = create_source_storyboard()

    result = engine.create_pilot_storyboard(
        source,
        target_duration_seconds=12,
    )

    editorial_positions = [
        index
        for index, scene in enumerate(
            result.scenes,
            start=1,
        )
        if scene.text_overlay.strip()
    ]

    assert editorial_positions

    assert editorial_positions[0] in (
        3,
        4,
    )

    for previous, current in zip(
        editorial_positions,
        editorial_positions[1:],
    ):
        gap = current - previous

        assert 3 <= gap <= 4


def test_editorial_text_has_maximum_four_words() -> None:
    engine = DynamicStoryboardEngine()

    source = create_source_storyboard()

    result = engine.create_pilot_storyboard(
        source,
        target_duration_seconds=12,
    )

    for scene in result.scenes:
        if scene.text_overlay.strip():
            assert len(
                scene.text_overlay.split()
            ) <= 4


def test_real_reason_generates_contextual_editorial_text() -> None:
    engine = DynamicStoryboardEngine()

    text = engine._build_editorial_text(
        "The real reason is surprisingly simple."
    )

    assert text == (
        "THE REAL REASON"
    )


def test_number_generates_editorial_text() -> None:
    engine = DynamicStoryboardEngine()

    text = engine._build_editorial_text(
        "This changed over 10000 years."
    )

    assert text == "10000 YEARS"


def test_contextual_scoring_prefers_strong_beat() -> None:
    engine = DynamicStoryboardEngine()

    weak_score = engine._editorial_score(
        "The pirate walks across the ship."
    )

    strong_score = engine._editorial_score(
        "The real reason is surprisingly simple."
    )

    assert strong_score > weak_score


def test_storyboard_has_image_prompts() -> None:
    engine = DynamicStoryboardEngine()

    source = create_source_storyboard()

    result = engine.create_pilot_storyboard(
        source,
        target_duration_seconds=12,
    )

    for scene in result.scenes:
        assert len(
            scene.image_prompt
        ) >= 10


def test_original_topic_is_preserved() -> None:
    engine = DynamicStoryboardEngine()

    source = create_source_storyboard()

    result = engine.create_pilot_storyboard(
        source,
        target_duration_seconds=12,
    )

    assert result.topic == (
        source.topic
    )


def test_empty_storyboard_fails() -> None:
    engine = DynamicStoryboardEngine()

    source = Storyboard(
        topic="Empty",
        target_duration_seconds=1,
        scenes=[],
        total_scene_duration_seconds=0.0,
        target_scene_duration_seconds=5.0,
    )

    with pytest.raises(
        ValueError,
        match="no scenes",
    ):
        engine.create_pilot_storyboard(
            source,
            target_duration_seconds=180,
        )


def test_invalid_target_duration_fails() -> None:
    engine = DynamicStoryboardEngine()

    source = create_source_storyboard()

    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        engine.create_pilot_storyboard(
            source,
            target_duration_seconds=0,
        )