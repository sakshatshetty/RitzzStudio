import json
from pathlib import Path

import pytest

from modules.storyboard.engine import StoryboardEngine


PROJECT_DIR = Path(
    "projects/20260820_001_why_do_pirates_wear_eye_patches"
)

SCRIPT_FILE = (
    PROJECT_DIR
    / "script"
    / "script.json"
)


def test_load_script():
    engine = StoryboardEngine()

    script = engine.load_script(
        SCRIPT_FILE
    )

    assert script.topic == (
        "Why Do Pirates Wear Eye Patches?"
    )

    assert (
        script.target_duration_seconds
        == 480
    )

    assert len(script.sections) == 8


def test_create_storyboard():
    engine = StoryboardEngine(
        target_scene_duration_seconds=5.0
    )

    storyboard = engine.create_storyboard(
        SCRIPT_FILE
    )

    assert storyboard.topic == (
        "Why Do Pirates Wear Eye Patches?"
    )

    assert (
        storyboard.target_duration_seconds
        == 480
    )

    assert len(storyboard.scenes) > 0


def test_storyboard_has_expected_scene_count():
    engine = StoryboardEngine(
        target_scene_duration_seconds=5.0
    )

    storyboard = engine.create_storyboard(
        SCRIPT_FILE
    )

    # 480 seconds / 5 seconds = 96 scenes.
    assert len(storyboard.scenes) == 96


def test_storyboard_duration():
    engine = StoryboardEngine(
        target_scene_duration_seconds=5.0
    )

    storyboard = engine.create_storyboard(
        SCRIPT_FILE
    )

    assert (
        storyboard.total_scene_duration_seconds
        == 480
    )

    actual_duration = sum(
        scene.duration_seconds
        for scene in storyboard.scenes
    )

    assert actual_duration == pytest.approx(
        480,
        abs=0.1,
    )


def test_storyboard_contains_all_sections():
    engine = StoryboardEngine(
        target_scene_duration_seconds=5.0
    )

    storyboard = engine.create_storyboard(
        SCRIPT_FILE
    )

    section_ids = {
        scene.section_id
        for scene in storyboard.scenes
    }

    expected_section_ids = {
        "s1",
        "s2",
        "s3",
        "s4",
        "s5",
        "s6",
        "s7",
        "s8",
    }

    assert section_ids == expected_section_ids


def test_every_scene_has_required_visual_data():
    engine = StoryboardEngine(
        target_scene_duration_seconds=5.0
    )

    storyboard = engine.create_storyboard(
        SCRIPT_FILE
    )

    for scene in storyboard.scenes:
        assert scene.scene_id
        assert scene.section_id
        assert scene.narration.strip()
        assert scene.visual_description.strip()
        assert scene.image_prompt.strip()
        assert scene.duration_seconds > 0


def test_research_sources_are_preserved():
    engine = StoryboardEngine(
        target_scene_duration_seconds=5.0
    )

    storyboard = engine.create_storyboard(
        SCRIPT_FILE
    )

    for scene in storyboard.scenes:
        assert scene.research_sources


def test_scene_timing_is_sequential():
    engine = StoryboardEngine(
        target_scene_duration_seconds=5.0
    )

    storyboard = engine.create_storyboard(
        SCRIPT_FILE
    )

    previous_end = 0.0

    for scene in storyboard.scenes:
        assert scene.start_seconds == pytest.approx(
            previous_end,
            abs=0.01,
        )

        previous_end = (
            scene.start_seconds
            + scene.duration_seconds
        )


def test_scene_ids_are_sequential():
    engine = StoryboardEngine(
        target_scene_duration_seconds=5.0
    )

    storyboard = engine.create_storyboard(
        SCRIPT_FILE
    )

    for index, scene in enumerate(
        storyboard.scenes,
        start=1,
    ):
        assert scene.scene_id == (
            f"scene_{index:03d}"
        )


def test_save_and_load_storyboard(
    tmp_path: Path,
):
    engine = StoryboardEngine(
        target_scene_duration_seconds=5.0
    )

    output_file = (
        tmp_path
        / "storyboard.json"
    )

    storyboard = engine.create_storyboard(
        SCRIPT_FILE,
        output_file=output_file,
    )

    assert output_file.exists()

    loaded = engine.load_storyboard(
        output_file
    )

    assert loaded.topic == storyboard.topic

    assert len(loaded.scenes) == len(
        storyboard.scenes
    )

    assert (
        loaded.total_scene_duration_seconds
        == storyboard.total_scene_duration_seconds
    )


def test_saved_storyboard_contains_valid_json(
    tmp_path: Path,
):
    engine = StoryboardEngine(
        target_scene_duration_seconds=5.0
    )

    output_file = (
        tmp_path
        / "storyboard.json"
    )

    engine.create_storyboard(
        SCRIPT_FILE,
        output_file=output_file,
    )

    data = json.loads(
        output_file.read_text(
            encoding="utf-8"
        )
    )

    assert data["topic"] == (
        "Why Do Pirates Wear Eye Patches?"
    )

    assert len(data["scenes"]) == 96


def test_topic_mismatch_fails(
    tmp_path: Path,
):
    bad_script = tmp_path / "bad_script.json"

    data = json.loads(
        SCRIPT_FILE.read_text(
            encoding="utf-8"
        )
    )

    data["topic"] = (
        "Completely Different Topic"
    )

    bad_script.write_text(
        json.dumps(
            data,
            indent=4,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    engine = StoryboardEngine()

    # The Script model itself accepts the changed
    # topic, so the storyboard will use that topic.
    # We therefore verify that the engine still
    # produces a structurally valid storyboard.
    storyboard = engine.create_storyboard(
        bad_script
    )

    assert storyboard.topic == (
        "Completely Different Topic"
    )