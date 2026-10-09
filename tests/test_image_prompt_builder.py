import pytest

from modules.image.prompt_builder import ImagePromptBuilder
from modules.storyboard.models import (
    StoryboardScene,
)
from modules.storyboard.visual_models import (
    SceneVisualContract,
    VisualRestriction,
    VisualWorldBible,
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
        "hand-drawn educational explainer illustration"
        in prompt
    )
    assert (
        "thick black marker-and-ink outlines"
        in prompt
    )
    assert (
        "flat colors"
        in prompt
    )
    assert (
        "simple shading"
        in prompt
    )

    assert (
        "educational-explainer artwork"
        in prompt
    )

    assert "bold readable poses" in prompt
    assert "controlled hand-drawn imperfection" in prompt
    assert "clear silhouettes" in prompt
    assert "enough simple, relevant props to explain the scene" in prompt


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
        "Relevant scene props: eye patch, ship wheel"
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


def test_prompt_forbids_text_on_objects_and_generated_marks() -> None:
    prompt = ImagePromptBuilder().build(sample_scene())

    assert "NO TEXT OF ANY KIND, including on physical objects." in prompt
    assert "watermarks" in prompt.lower()
    assert "If the narration mentions writing, show the object without reproducing" in prompt


def test_default_character_profile_and_scene_era_lock_are_included() -> None:
    scene = sample_scene().model_copy(
        update={
            "visual_contract": SceneVisualContract(
                scene_id="scene_001",
                purpose="EXPLAIN",
                subject="An ancient human",
                action="sleeps on a woven mat",
                environment="A prehistoric shelter",
                historical_context="Deep prehistory; before powered technology.",
                ambiguity_resolution="Show a period-appropriate sleeping place.",
            )
        }
    )

    prompt = ImagePromptBuilder().build(scene)

    assert "When the recurring RITZZ host appears" in prompt
    assert "ERA LOCK: Depict the period and setting stated in this scene's" in prompt
    assert "Do not mix eras" in prompt
    assert "Use one unified moment and location" in prompt


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
        "all generated text."
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


def test_legacy_editorial_text_is_ignored_in_video_image_prompts() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "MYSTERY"
    scene.callout_position = "lower_left"

    prompt = builder.build(scene)

    assert "MYSTERY" not in prompt
    assert "NO TEXT." in prompt
    assert "DO NOT DRAW EDITORIAL CALLOUT TEXT." in prompt


def test_legacy_editorial_fields_do_not_override_visual_contract():
    scene = sample_scene().model_copy(
        update={
            "text_overlay": "SURVIVAL",
            "callout_position": "middle_right",
            "visual_contract": SceneVisualContract(
                scene_id="scene_001",
                purpose="SHOW_PROCESS",
                subject="A sailor's face and hand",
                action="raises a lantern",
                environment="A ship deck",
                historical_context="A historical sailing vessel",
                required_objects=["wooden lantern", "ship wheel"],
                ambiguity_resolution="Show a physical lantern.",
            ),
        }
    )

    prompt = ImagePromptBuilder().build(scene)

    assert "SCENE ACTION: raises a lantern" in prompt
    assert "REQUIRED OBJECTS: wooden lantern, ship wheel" in prompt


def test_prompt_uses_current_sentence_and_neighbor_context_with_clear_priority():
    scene = sample_scene().model_copy(
        update={
            "sentence": "The pirate hides beneath the cargo deck.",
            "previous_sentence": "The sailor heard footsteps overhead.",
            "next_sentence": "The crew searches the upper deck.",
        }
    )

    prompt = ImagePromptBuilder().build(
        scene,
        project_topic="Why Do Pirates Wear Eye Patches?",
    )

    assert "FULL PROJECT TOPIC: Why Do Pirates Wear Eye Patches?" in prompt
    assert (
        "CURRENT SENTENCE — PRIMARY VISUAL INSTRUCTION: "
        "The pirate hides beneath the cargo deck."
    ) in prompt
    assert (
        "PREVIOUS SENTENCE — continuity context only: "
        "The sailor heard footsteps overhead."
    ) in prompt
    assert (
        "NEXT SENTENCE — continuity context only: "
        "The crew searches the upper deck."
    ) in prompt
    assert prompt.index("CURRENT SENTENCE") < prompt.index("PREVIOUS SENTENCE")
    assert "current sentence determines" in prompt
    assert "Context must clarify the current sentence" in prompt
    assert "NO TEXT." in prompt


def test_prompt_contains_stable_character_reference_and_environment_context():
    scene = sample_scene().model_copy(
        update={
            "previous_sentence": "The sailor heard footsteps overhead.",
            "next_sentence": "The crew searches the upper deck.",
            "visual_contract": SceneVisualContract(
                scene_id="scene_001",
                purpose="SHOW_PROCESS",
                subject="The same sailor from the previous scene",
                action="hides under cargo",
                environment="Ship cargo deck with barrels, crates, a ladder, and lantern",
                historical_context="A period wooden sailing ship",
                required_objects=["barrels", "crates", "ladder", "lantern"],
                ambiguity_resolution="Show the sailor hiding below deck.",
                continuity_requirements=["Preserve the sailor's eye patch and red shirt."],
            ),
        }
    )
    builder = ImagePromptBuilder(character_profile="Same round head and red shirt")

    prompt = builder.build(scene, project_topic="Pirate history")

    assert "Same round head and red shirt" in prompt
    assert "Keep this character design consistent" in prompt
    assert "Preserve the sailor's eye patch and red shirt." in prompt
    assert "barrels, crates, ladder, lantern" in prompt
    assert "SURVIVAL" not in prompt
    assert "NO TEXT." in prompt


def test_editorial_position_map_includes_all_clear_safe_zones():
    assert set(ImagePromptBuilder.EDITORIAL_POSITION_MAP) == {
        "top_left",
        "top_center",
        "top_right",
        "middle_left",
        "middle_center",
        "middle_right",
        "lower_left",
        "lower_center",
        "lower_right",
    }


def test_legacy_editorial_text_does_not_change_image_generation_prompt() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "WILDSIZE"

    prompt = builder.build(scene)

    assert "WILDSIZE" not in prompt
    assert "NO TEXT." in prompt


def test_legacy_editorial_text_preserves_colored_illustration_style() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "MYSTERY"

    prompt = builder.build(scene)

    assert "flat colors" in prompt
    assert "MYSTERY" not in prompt


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


def test_legacy_editorial_text_is_not_allowed_in_video_artwork() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "MYSTERY"

    prompt = builder.build(scene)

    assert "MYSTERY" not in prompt
    assert "NO TEXT." in prompt


def test_legacy_editorial_position_does_not_change_composition() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "MYSTERY"
    scene.callout_position = "lower_left"

    prompt = builder.build(scene)

    assert "lower-left negative space" not in prompt
    assert "MYSTERY" not in prompt


def test_legacy_editorial_text_is_not_requested_as_a_graphic_element() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "LARGER"

    prompt = builder.build(scene)

    assert "NO TEXT." in prompt
    assert "LARGER" not in prompt


def test_legacy_editorial_text_does_not_change_negative_text_instruction() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "LARGER"

    prompt = builder.build(scene)

    assert "Avoid photorealism" in prompt
    assert "NO TEXT." in prompt


def test_legacy_editorial_text_is_not_trimmed_into_a_video_overlay() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = (
        "   REASON   "
    )

    prompt = builder.build(scene)

    assert "REASON" not in prompt


def test_video_image_prompt_never_embeds_legacy_editorial_text() -> None:
    builder = ImagePromptBuilder()

    scene = sample_scene()
    scene.text_overlay = "MYSTERY"

    prompt = builder.build(scene)

    assert "MYSTERY" not in prompt
    assert "NO TEXT." in prompt


def test_prompt_keeps_the_current_sentence_dominant_and_environment_readable() -> None:
    builder = ImagePromptBuilder()

    prompt = builder.build(
        sample_scene()
    )

    assert "Show the current sentence as one complete visual idea." in prompt
    assert "foreground action dominant and the background supportive" in prompt
    assert "Use multiple characters or objects when the sentence requires them." in prompt


def test_prompt_does_not_turn_scene_into_infographic() -> None:
    builder = ImagePromptBuilder()

    prompt = builder.build(
        sample_scene()
    )

    assert "NO INFOGRAPHICS." in prompt


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


def test_all_contextually_supplied_props_are_available_to_the_image_prompt() -> None:
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
        "Relevant scene props: eye patch, ship wheel, rope, barrel, treasure chest"
        in prompt
    )
