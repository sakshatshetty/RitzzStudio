from typing import cast

from modules.image.prompt_builder import ImagePromptBuilder
from modules.storyboard.models import (
    CameraMotion,
    StoryboardScene,
)


def sample_scene() -> StoryboardScene:
    return StoryboardScene(
        scene_id="scene_001",
        section_id="section_001",
        start_seconds=0,
        duration_seconds=5,
        narration="A pirate stands on a wooden ship.",
        visual_style="stickman",
        visual_description=(
            "A pirate standing on a wooden ship."
        ),
        character_action=(
            "The pirate looks toward the viewer."
        ),
        background="Wooden pirate ship deck.",
        props=[
            "eye patch",
            "ship wheel",
        ],
        text_overlay="",
        camera_motion="static",
        transition="cut",
        research_sources=[
            "source-1",
        ],
        image_prompt=(
            "A simple pirate illustration."
        ),
    )


def test_default_style_is_used() -> None:
    builder = ImagePromptBuilder()

    prompt = builder.build(
        sample_scene()
    )

    assert (
        "Simple 2D cartoon illustration"
        in prompt
    )
    assert (
        "thick black outlines"
        in prompt
    )
    assert (
        "flat colors"
        in prompt
    )
    assert (
        "very minimal shading"
        in prompt
    )
    assert (
        "YouTube explainer animation style"
        in prompt
    )


def test_prompt_contains_landscape_composition() -> None:
    builder = ImagePromptBuilder()

    prompt = builder.build(
        sample_scene()
    )

    assert (
        "Landscape 16:9 composition."
        in prompt
    )


def test_prompt_contains_scene_description() -> None:
    builder = ImagePromptBuilder()

    prompt = builder.build(
        sample_scene()
    )

    assert (
        "Scene: A pirate standing on a wooden ship."
        in prompt
    )


def test_prompt_contains_character_action() -> None:
    builder = ImagePromptBuilder()

    prompt = builder.build(
        sample_scene()
    )

    assert (
        "Action: The pirate looks toward the viewer."
        in prompt
    )


def test_prompt_contains_background() -> None:
    builder = ImagePromptBuilder()

    prompt = builder.build(
        sample_scene()
    )

    assert (
        "Background: Wooden pirate ship deck."
        in prompt
    )


def test_prompt_contains_props() -> None:
    builder = ImagePromptBuilder()

    prompt = builder.build(
        sample_scene()
    )

    assert (
        "Props: eye patch, ship wheel"
        in prompt
    )


def test_prompt_without_editorial_text_does_not_request_text() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = ""

    prompt = builder.build(scene)

    assert (
        "Editorial text inside the illustration"
        not in prompt
    )

    assert "NO TEXT." in prompt
    assert "NO TITLES." in prompt
    assert "NO HEADLINES." in prompt
    assert "NO LABELS." in prompt
    assert "NO ARROWS." in prompt
    assert "NO CAPTIONS." in prompt
    assert "NO SUBTITLES." in prompt
    assert "NO SPEECH BUBBLES." in prompt
    assert "NO INFOGRAPHICS." in prompt
    assert "NO DIAGRAMS." in prompt
    assert "NO TIMELINES." in prompt
    assert "NO ANNOTATIONS." in prompt
    assert "NO EXPLANATORY WRITING." in prompt


def test_prompt_without_editorial_text_contains_negative_style() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = ""

    prompt = builder.build(scene)

    assert (
        "Avoid photorealism"
        in prompt
    )

    assert (
        "unnecessary text."
        in prompt
    )


def test_prompt_without_editorial_text_does_not_use_editorial_instruction() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = ""

    prompt = builder.build(scene)

    assert (
        "Editorial text inside the illustration:"
        not in prompt
    )

    assert (
        "not a subtitle or caption"
        not in prompt
    )


def test_prompt_contains_camera_motion() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.camera_motion = "slow_zoom_in"

    prompt = builder.build(scene)

    assert (
        "Slow gentle zoom in."
        in prompt
    )


def test_prompt_adds_editorial_text_when_present() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "THE MYSTERY"

    prompt = builder.build(scene)

    assert (
        'Editorial text inside the illustration: '
        '"THE MYSTERY".'
        in prompt
    )


def test_editorial_text_uses_handwritten_typography() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "WILD SIZE"

    prompt = builder.build(scene)

    assert (
        "simple, clean, hand-drawn handwritten lettering"
        in prompt
    )

    assert (
        "casual handwritten marker or hand-lettered"
        in prompt
    )

    assert (
        "medium-large and clearly readable"
        in prompt
    )

    assert (
        "visually noticeable but still secondary"
        in prompt
    )


def test_editorial_text_uses_plain_black_or_white() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "THE MYSTERY"

    prompt = builder.build(scene)

    assert (
        "plain black or plain white"
        in prompt
    )


def test_editorial_text_is_not_cursive() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "THE MYSTERY"

    prompt = builder.build(scene)

    assert (
        "Do not use cursive writing"
        in prompt
    )


def test_editorial_text_avoids_decorative_effects() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "THE MYSTERY"

    prompt = builder.build(scene)

    assert (
        "No decorative lettering"
        in prompt
    )

    assert (
        "no thick outline"
        in prompt
    )

    assert (
        "no 3D effects"
        in prompt
    )

    assert (
        "no gradients"
        in prompt
    )

    assert (
        "no bright colors"
        in prompt
    )

    assert (
        "no shadows"
        in prompt
    )

    assert (
        "no graphic text effects"
        in prompt
    )


def test_editorial_text_avoids_large_headline_treatment() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "THE MYSTERY"

    prompt = builder.build(scene)

    assert (
        "large headline text"
        in prompt
    )

    assert (
        "oversized display typography"
        in prompt
    )

    assert (
        "bold display typography"
        in prompt
    )


def test_editorial_text_avoids_colored_text() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "THE MYSTERY"

    prompt = builder.build(scene)

    assert (
        "multicolored text"
        in prompt
    )

    assert (
        "yellow text"
        in prompt
    )

    assert (
        "bright colored text"
        in prompt
    )


def test_editorial_text_avoids_graphic_text_elements() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "10× LARGER"

    prompt = builder.build(scene)

    assert (
        "text banners"
        in prompt
    )

    assert (
        "burst shapes"
        in prompt
    )

    assert (
        "gradient text"
        in prompt
    )

    assert (
        "drop shadows"
        in prompt
    )


def test_editorial_text_changes_negative_text_instruction() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "10× LARGER"

    prompt = builder.build(scene)

    assert (
        "any text beyond the requested editorial callout"
        in prompt
    )


def test_editorial_text_is_trimmed() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = (
        "   THE REAL REASON   "
    )

    prompt = builder.build(scene)

    assert (
        'Editorial text inside the illustration: '
        '"THE REAL REASON".'
        in prompt
    )

    assert (
        '"   THE REAL REASON   "'
        not in prompt
    )


def test_editorial_text_is_part_of_artwork() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "THE MYSTERY"

    prompt = builder.build(scene)

    assert (
        "The editorial text is part of the artwork"
        in prompt
    )

    assert (
        "not a subtitle or caption"
        in prompt
    )


def test_prompt_contains_simple_visual_direction() -> None:
    builder = ImagePromptBuilder()

    prompt = builder.build(
        sample_scene()
    )

    assert (
        "Keep the scene visually simple."
        in prompt
    )

    assert (
        "Use one main visual idea."
        in prompt
    )

    assert (
        "Use one main character whenever possible."
        in prompt
    )

    assert (
        "Use only the necessary props."
        in prompt
    )

    assert (
        "Keep the background simple and secondary."
        in prompt
    )


def test_prompt_does_not_turn_scene_into_infographic() -> None:
    builder = ImagePromptBuilder()

    prompt = builder.build(
        sample_scene()
    )

    assert (
        "Do not turn the scene into an infographic."
        in prompt
    )


def test_static_camera() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.camera_motion = "static"

    prompt = builder.build(scene)

    assert (
        "Static camera."
        in prompt
    )


def test_slow_zoom_in_camera() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.camera_motion = "slow_zoom_in"

    prompt = builder.build(scene)

    assert (
        "Slow gentle zoom in."
        in prompt
    )


def test_slow_zoom_out_camera() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.camera_motion = "slow_zoom_out"

    prompt = builder.build(scene)

    assert (
        "Slow gentle zoom out."
        in prompt
    )


def test_pan_left_camera() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.camera_motion = "pan_left"

    prompt = builder.build(scene)

    assert (
        "Gentle camera pan left."
        in prompt
    )


def test_pan_right_camera() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.camera_motion = "pan_right"

    prompt = builder.build(scene)

    assert (
        "Gentle camera pan right."
        in prompt
    )


def test_pan_up_camera() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.camera_motion = "pan_up"

    prompt = builder.build(scene)

    assert (
        "Gentle camera pan upward."
        in prompt
    )


def test_pan_down_camera() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.camera_motion = "pan_down"

    prompt = builder.build(scene)

    assert (
        "Gentle camera pan downward."
        in prompt
    )


def test_all_camera_motion_variants_are_supported() -> None:
    builder = ImagePromptBuilder()

    expected: dict[
        CameraMotion,
        str,
    ] = {
        "static": "Static camera.",
        "slow_zoom_in": "Slow gentle zoom in.",
        "slow_zoom_out": "Slow gentle zoom out.",
        "pan_left": "Gentle camera pan left.",
        "pan_right": "Gentle camera pan right.",
        "pan_up": "Gentle camera pan upward.",
        "pan_down": "Gentle camera pan downward.",
    }

    for motion, expected_text in expected.items():
        scene = sample_scene()

        scene.camera_motion = cast(
            CameraMotion,
            motion,
        )

        prompt = builder.build(scene)

        assert (
            expected_text
            in prompt
        )


def test_custom_base_style_is_supported() -> None:
    builder = ImagePromptBuilder(
        base_style="Custom visual style."
    )

    prompt = builder.build(
        sample_scene()
    )

    assert (
        "Custom visual style."
        in prompt
    )

    assert (
        "Simple 2D cartoon illustration"
        not in prompt
    )


def test_character_profile_is_included() -> None:
    character_profile = (
        "A friendly stickman pirate with "
        "a black hat."
    )

    builder = ImagePromptBuilder(
        character_profile=character_profile
    )

    prompt = builder.build(
        sample_scene()
    )

    assert (
        "Character design reference for this video:"
        in prompt
    )

    assert (
        character_profile
        in prompt
    )

    assert (
        "Keep this character design consistent "
        "throughout this video."
        in prompt
    )


def test_empty_character_profile_is_not_added() -> None:
    builder = ImagePromptBuilder(
        character_profile=""
    )

    prompt = builder.build(
        sample_scene()
    )

    assert (
        "Character design reference for this video:"
        not in prompt
    )


def test_first_three_props_are_used() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()

    scene.props = [
        "eye patch",
        "ship wheel",
        "rope",
        "barrel",
        "treasure chest",
    ]

    prompt = builder.build(scene)

    assert (
        "Props: eye patch, ship wheel, rope"
        in prompt
    )

    assert (
        "barrel"
        not in prompt
    )

    assert (
        "treasure chest"
        not in prompt
    )