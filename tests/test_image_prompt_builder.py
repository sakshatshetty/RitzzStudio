from modules.image.prompt_builder import (
    ImagePromptBuilder,
)
from modules.storyboard.models import StoryboardScene


def create_scene() -> StoryboardScene:
    return StoryboardScene(
        scene_id="scene_001",
        section_id="s1",
        start_seconds=0,
        duration_seconds=5,
        narration="Why do pirates wear eye patches?",
        visual_style="stickman",
        visual_description=(
            "A pirate standing on the deck of a wooden ship."
        ),
        character_action=(
            "The pirate points toward his eye patch."
        ),
        background=(
            "A simple wooden pirate ship at sea."
        ),
        props=[
            "eye patch",
            "ship wheel",
        ],
        text_overlay="Why the eye patch?",
        camera_motion="static",
        transition="cut",
        research_sources=[
            "source-1",
        ],
        image_prompt=(
            "Simple 2D cartoon stickman pirate "
            "standing on a wooden ship."
        ),
    )


def test_default_style_is_included() -> None:
    builder = ImagePromptBuilder()
    scene = create_scene()

    prompt = builder.build(scene)

    assert (
        "Simple 2D stickman cartoon illustration"
        in prompt
    )

    assert "thick black outlines" in prompt
    assert "flat colors" in prompt
    assert "minimal shading" in prompt


def test_visual_description_is_included() -> None:
    builder = ImagePromptBuilder()
    scene = create_scene()

    prompt = builder.build(scene)

    assert (
        "A pirate standing on the deck of a wooden ship."
        in prompt
    )


def test_character_action_is_included() -> None:
    builder = ImagePromptBuilder()
    scene = create_scene()

    prompt = builder.build(scene)

    assert (
        "The pirate points toward his eye patch."
        in prompt
    )


def test_background_is_included() -> None:
    builder = ImagePromptBuilder()
    scene = create_scene()

    prompt = builder.build(scene)

    assert (
        "A simple wooden pirate ship at sea."
        in prompt
    )


def test_props_are_included() -> None:
    builder = ImagePromptBuilder()
    scene = create_scene()

    prompt = builder.build(scene)

    assert "eye patch, ship wheel" in prompt


def test_text_overlay_is_included() -> None:
    builder = ImagePromptBuilder()
    scene = create_scene()

    prompt = builder.build(scene)

    assert "Why the eye patch?" in prompt


def test_camera_motion_is_included() -> None:
    builder = ImagePromptBuilder()
    scene = create_scene()

    prompt = builder.build(scene)

    assert "static composition" in prompt


def test_zoom_camera_motion() -> None:
    builder = ImagePromptBuilder()
    scene = create_scene()

    scene.camera_motion = "slow_zoom_in"

    prompt = builder.build(scene)

    assert "subtle zoom-in composition" in prompt


def test_custom_style() -> None:
    builder = ImagePromptBuilder(
        base_style=(
            "Custom Ritzz visual style."
        )
    )

    scene = create_scene()

    prompt = builder.build(scene)

    assert (
        "Custom Ritzz visual style."
        in prompt
    )


def test_negative_style_is_included() -> None:
    builder = ImagePromptBuilder()
    scene = create_scene()

    prompt = builder.build(scene)

    assert "Avoid photorealism" in prompt
    assert "3D rendering" in prompt