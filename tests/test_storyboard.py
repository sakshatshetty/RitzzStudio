import pytest
from pydantic import ValidationError

from modules.storyboard.models import (
    Storyboard,
    StoryboardScene,
)


def test_storyboard_scene_model():
    scene = StoryboardScene(
        scene_id="scene_001",
        section_id="s1",
        start_seconds=0,
        duration_seconds=5,
        narration="A pirate appears on screen.",
        visual_style="stickman",
        visual_description=(
            "A simple stick-man pirate standing on a ship."
        ),
        character_action="Standing and looking toward the viewer.",
        background="Simple ocean and wooden ship.",
        props=["eyepatch", "pirate hat"],
        text_overlay="DID PIRATES REALLY WEAR EYE PATCHES?",
        camera_motion="slow_zoom_in",
        transition="cut",
        research_sources=["source_001"],
        image_prompt=(
            "Simple hand-drawn stick-man pirate on a wooden ship, "
            "clean white background, black outlines."
        ),
    )

    assert scene.scene_id == "scene_001"
    assert scene.duration_seconds == 5
    assert scene.visual_style == "stickman"


def test_storyboard_scene_duration_validation():
    with pytest.raises(ValidationError):
        StoryboardScene(
            scene_id="scene_001",
            section_id="s1",
            start_seconds=0,
            duration_seconds=31,
            narration="Test narration.",
            visual_description=(
                "A simple illustrated scene."
            ),
            image_prompt=(
                "A simple illustrated stick-man scene."
            ),
        )


def test_storyboard_model():
    scene = StoryboardScene(
        scene_id="scene_001",
        section_id="s1",
        start_seconds=0,
        duration_seconds=5,
        narration="A pirate appears.",
        visual_description=(
            "A stick-man pirate standing on a ship."
        ),
        image_prompt=(
            "A simple hand-drawn stick-man pirate."
        ),
    )

    storyboard = Storyboard(
        topic="Why Do Pirates Wear Eye Patches?",
        target_duration_seconds=480,
        scenes=[scene],
        total_scene_duration_seconds=5,
    )

    assert storyboard.topic == "Why Do Pirates Wear Eye Patches?"
    assert len(storyboard.scenes) == 1
    assert storyboard.target_scene_duration_seconds == 5.0


def test_storyboard_requires_image_prompt():
    with pytest.raises(ValidationError):
        StoryboardScene(
            scene_id="scene_001",
            section_id="s1",
            start_seconds=0,
            duration_seconds=5,
            narration="A pirate appears.",
            visual_description=(
                "A simple illustrated pirate."
            ),
            image_prompt="short",
        )