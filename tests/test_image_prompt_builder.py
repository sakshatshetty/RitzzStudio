from modules.image.prompt_builder import ImagePromptBuilder
from modules.storyboard.models import CameraMotion, StoryboardScene


def sample_scene() -> StoryboardScene:
    return StoryboardScene(
        scene_id="scene_001",
        section_id="section_001",
        start_seconds=0.0,
        duration_seconds=5.0,
        narration="A pirate stands on the deck of a ship.",
        visual_style="stickman",
        visual_description=(
            "A simple cartoon pirate standing on a wooden ship deck."
        ),
        character_action=(
            "The pirate points toward one covered eye."
        ),
        background=(
            "Simple ocean and ship deck background."
        ),
        props=[
            "eye patch",
            "ship wheel",
        ],
        text_overlay="",
        camera_motion="static",
        transition="cut",
        research_sources=[],
        image_prompt="Pirate on a ship.",
    )


def test_prompt_contains_ritzz_visual_style():
    builder = ImagePromptBuilder()

    prompt = builder.build(sample_scene())

    assert "Simple 2D cartoon illustration" in prompt
    assert "thick black outlines" in prompt
    assert "flat colors" in prompt
    assert "very minimal shading" in prompt
    assert "YouTube explainer animation style" in prompt


def test_prompt_contains_landscape_composition():
    builder = ImagePromptBuilder()

    prompt = builder.build(sample_scene())

    assert "Landscape 16:9 composition." in prompt


def test_prompt_contains_scene_description():
    builder = ImagePromptBuilder()

    prompt = builder.build(sample_scene())

    assert (
        "A simple cartoon pirate standing on a wooden ship deck."
        in prompt
    )


def test_prompt_contains_character_action():
    builder = ImagePromptBuilder()

    prompt = builder.build(sample_scene())

    assert (
        "The pirate points toward one covered eye."
        in prompt
    )


def test_prompt_contains_background():
    builder = ImagePromptBuilder()

    prompt = builder.build(sample_scene())

    assert (
        "Simple ocean and ship deck background."
        in prompt
    )


def test_prompt_contains_props():
    builder = ImagePromptBuilder()

    prompt = builder.build(sample_scene())

    assert "Props: eye patch, ship wheel" in prompt


def test_prompt_contains_camera_motion():
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.camera_motion = "slow_zoom_in"

    prompt = builder.build(scene)

    assert "Slow gentle zoom in." in prompt


def test_prompt_contains_negative_style():
    builder = ImagePromptBuilder()

    prompt = builder.build(sample_scene())

    assert "Avoid photorealism" in prompt
    assert "realistic humans" in prompt
    assert "3D rendering" in prompt
    assert "Avoid" in prompt


def test_prompt_does_not_force_specific_character():
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.visual_description = (
        "A simple cartoon scientist standing beside a laboratory table."
    )
    scene.character_action = (
        "The scientist examines a glowing test tube."
    )
    scene.background = (
        "A simple clean laboratory."
    )
    scene.props = [
        "test tube",
        "laboratory table",
    ]

    prompt = builder.build(scene)

    assert "Simple 2D cartoon illustration" in prompt
    assert "scientist" in prompt
    assert "pirate" not in prompt
    assert "eye patch" not in prompt


def test_prompt_adds_editorial_text_when_present():
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "THE MYSTERY"

    prompt = builder.build(scene)

    assert (
        'Editorial text inside the illustration: "THE MYSTERY".'
        in prompt
    )


def test_editorial_text_is_described_as_visual_callout():
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "WILD SIZE"

    prompt = builder.build(scene)

    assert "short, large, bold, readable" in prompt
    assert "naturally integrated into the composition" in prompt
    assert "editorial artwork" in prompt
    assert "not a subtitle or caption" in prompt


def test_editorial_text_is_not_forced_when_empty():
    builder = ImagePromptBuilder()

    prompt = builder.build(sample_scene())

    assert "Editorial text inside the illustration" not in prompt
    assert "not a subtitle or caption" not in prompt


def test_editorial_text_changes_negative_text_instruction():
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "10× LARGER"

    prompt = builder.build(scene)

    assert (
        "any text beyond the requested editorial callout"
        in prompt
    )

    assert (
        "unnecessary text."
        not in prompt
    )


def test_editorial_text_is_trimmed():
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "  THE REAL REASON  "

    prompt = builder.build(scene)

    assert (
        'Editorial text inside the illustration: "THE REAL REASON".'
        in prompt
    )


def test_custom_base_style_is_supported():
    builder = ImagePromptBuilder(
        base_style="Custom illustration style."
    )

    prompt = builder.build(sample_scene())

    assert "Custom illustration style." in prompt
    assert "Simple 2D cartoon illustration" not in prompt


def test_all_camera_motion_variants_are_supported():
    builder = ImagePromptBuilder()

    expected: dict[CameraMotion, str] = {
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
        scene.camera_motion = motion

        prompt = builder.build(scene)

        assert expected_text in prompt