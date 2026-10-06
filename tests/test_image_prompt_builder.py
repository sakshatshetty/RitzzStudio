import pytest

from modules.image.prompt_builder import ImagePromptBuilder
from modules.storyboard.visual_models import (
    SceneVisualContract,
    VisualRestriction,
    VisualWorldBible,
)
from modules.storyboard.models import (
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

    assert "Hand-drawn educational explainer illustration" in prompt
    assert "rough marker and pen ink drawing" in prompt
    assert "annotation-like storyboard frame" in prompt
    assert "controlled human imperfection" in prompt
    assert "subtle natural line-weight variation" in prompt
    assert "organic slightly uneven shapes" in prompt
    assert "clean and readable rather than messy or unfinished" in prompt


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
    assert "DO NOT DRAW EDITORIAL CALLOUT TEXT." in prompt
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

    assert "Static camera; the video uses hard cuts between still images." in prompt


def test_prompt_adds_editorial_text_when_present() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "MYSTERY"
    scene.callout_position = "lower_left"

    prompt = builder.build(scene)

    assert "exact editorial word MYSTERY" in prompt
    assert "intentionally part of the generated image" in prompt
    assert "Do not add any other letters" in prompt


def test_editorial_text_is_included_in_image_generation_prompt() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "WILDSIZE"

    prompt = builder.build(scene)

    assert "exact editorial word WILDSIZE" in prompt
    assert "intentionally part of the generated image" in prompt


def test_editorial_text_does_not_change_the_colored_illustration_style() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "MYSTERY"

    prompt = builder.build(scene)

    assert "Keep the illustration fully colored" in prompt
    assert "normal RITZZ flat-color palette" in prompt


def test_prompt_includes_project_world_and_scene_contract() -> None:
    world = VisualWorldBible(
        topic="Test Topic",
        historical=True,
        time_period="Around 1200 CE",
        geography="Coastal settlements",
        civilization_or_society="A medieval coastal society",
        technology_level="Hand-powered tools",
        built_environment="Timber buildings",
        clothing="Wool and linen garments",
        transportation="Sailing vessels",
        tools_and_weapons="Hand-forged tools",
        containers_and_materials="Wood and pottery",
        architecture="Timber structures",
        natural_environment="Rocky coast",
        social_context="Small port communities",
        visual_style="Simple hand-drawn 2D cartoon",
        technology_ceiling="No powered machinery or modern materials",
        forbidden_visuals=[
            VisualRestriction(
                category="anachronism",
                description="No electric lighting.",
                research_basis="The approved research places the scene in 1200 CE.",
            )
        ],
    )
    scene = sample_scene().model_copy(
        update={
            "visual_contract": SceneVisualContract(
                scene_id="scene_001",
                purpose="SHOW_PROCESS",
                subject="A sailor",
                action="raises a wooden lantern",
                environment="The deck of a timber sailing ship",
                historical_context="A medieval coastal setting",
                required_objects=["wooden lantern"],
                forbidden_objects=["electric lamp"],
                ambiguity_resolution="Show a physical lantern, not a metaphor.",
            )
        }
    )

    prompt = ImagePromptBuilder(visual_world=world).build(scene)

    assert "PROJECT VISUAL WORLD" in prompt
    assert "No powered machinery or modern materials" in prompt
    assert "No electric lighting." in prompt
    assert "SCENE PURPOSE: SHOW_PROCESS" in prompt
    assert "SCENE ACTION: raises a wooden lantern" in prompt
    assert "REQUIRED OBJECTS: wooden lantern" in prompt
    assert "FORBIDDEN OBJECTS: electric lamp" in prompt


def test_editorial_text_prompt_allows_only_the_assigned_word() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "MYSTERY"

    prompt = builder.build(scene)

    assert "exact editorial word MYSTERY" in prompt
    assert "Do not add any other letters, words, captions, labels, or typography." in prompt


def test_editorial_text_prompt_preserves_negative_space_for_callout() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "MYSTERY"
    scene.callout_position = "lower_left"

    prompt = builder.build(scene)

    assert "lower-left negative space" in prompt
    assert "exact editorial word MYSTERY" in prompt


def test_editorial_text_avoids_graphic_text_elements() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "LARGER"

    prompt = builder.build(scene)

    assert "Do not add any other letters" in prompt


def test_editorial_text_changes_negative_text_instruction() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "LARGER"

    prompt = builder.build(scene)

    assert "Avoid photorealism" in prompt


def test_editorial_text_is_trimmed() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = (
        "   REASON   "
    )

    prompt = builder.build(scene)

    assert "exact editorial word REASON" in prompt


def test_editorial_text_is_part_of_generated_image() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "MYSTERY"

    prompt = builder.build(scene)

    assert "intentionally part of the generated image" in prompt


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


@pytest.mark.parametrize(
    "camera_motion",
    [
        "static",
        "slow_zoom_in",
        "slow_zoom_out",
        "pan_left",
        "pan_right",
        "pan_up",
        "pan_down",
    ],
)
def test_legacy_camera_motion_metadata_keeps_prompt_static(camera_motion) -> None:
    scene = sample_scene()
    scene.camera_motion = camera_motion

    prompt = ImagePromptBuilder().build(scene)

    assert "Static camera; the video uses hard cuts between still images." in prompt
    assert "gentle zoom" not in prompt
    assert "camera pan" not in prompt


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
