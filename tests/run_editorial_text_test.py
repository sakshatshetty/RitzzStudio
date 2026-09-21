import sys
from pathlib import Path


# Add project root to Python import path when this file
# is executed directly with:
# python tests/run_editorial_text_test.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from modules.image.engine import ImageEngine
from modules.image.prompt_builder import ImagePromptBuilder
from modules.image.providers.openai import OpenAIImageProvider
from modules.storyboard.models import StoryboardScene


PROJECT_DIR = (
    PROJECT_ROOT
    / "projects"
    / "20260820_001_why_do_pirates_wear_eye_patches"
)

OUTPUT_DIR = PROJECT_DIR / "images" / "editorial_text_test"


PIRATE_CHARACTER_PROFILE = (
    "A simple friendly mischievous stickman pirate. "
    "Round white face. "
    "One black eye patch over the left eye. "
    "Black pirate hat with a small white skull symbol. "
    "Red bandana tied around the head. "
    "Very simple black stick body. "
    "Simple black pirate boots. "
    "Keep the same face, hat, bandana, eye patch, "
    "body proportions, and clothing throughout this video. "
    "Do not redesign or replace the character."
)


TEST_SCENES = [
    {
        "scene_id": "editorial_001",
        "visual_description": (
            "The pirate stands on the deck of his wooden ship, "
            "looking puzzled while pointing toward his eye patch."
        ),
        "character_action": (
            "The pirate points at his eye patch with a curious expression."
        ),
        "background": (
            "Simple wooden pirate ship deck with blue ocean and sky."
        ),
        "props": ["ship wheel", "rope"],
        "text_overlay": "THE MYSTERY",
    },
    {
        "scene_id": "editorial_002",
        "visual_description": (
            "The pirate examines his eye patch closely as if "
            "he has discovered an important historical clue."
        ),
        "character_action": (
            "The pirate holds the eye patch and looks surprised."
        ),
        "background": (
            "Simple dark wooden ship interior with a small lantern."
        ),
        "props": ["lantern", "wooden crate"],
        "text_overlay": "THE REAL REASON",
    },
    {
        "scene_id": "editorial_003",
        "visual_description": (
            "The pirate stands beside a giant exaggerated comparison "
            "showing a normal object next to something ten times larger."
        ),
        "character_action": (
            "The pirate points dramatically toward the much larger object."
        ),
        "background": (
            "Simple bright beach with blue ocean and clear sky."
        ),
        "props": ["large comparison object"],
        "text_overlay": "10× LARGER",
    },
]


def build_scene(data: dict) -> StoryboardScene:
    return StoryboardScene(
        scene_id=data["scene_id"],
        section_id="editorial_test",
        start_seconds=0,
        duration_seconds=5,
        narration="Editorial text generation test.",
        visual_style="stickman",
        visual_description=data["visual_description"],
        character_action=data["character_action"],
        background=data["background"],
        props=data["props"],
        text_overlay=data["text_overlay"],
        camera_motion="static",
        transition="cut",
        research_sources=[],
        image_prompt="Editorial text generation test.",
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    provider = OpenAIImageProvider()
    image_engine = ImageEngine(provider)

    prompt_builder = ImagePromptBuilder(
        character_profile=PIRATE_CHARACTER_PROFILE
    )

    print()
    print("RITZZ EDITORIAL TEXT TEST")
    print("=" * 60)
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Output directory: {OUTPUT_DIR}")
    print()

    for index, scene_data in enumerate(TEST_SCENES, start=1):
        scene = build_scene(scene_data)

        prompt = prompt_builder.build(scene)

        request = image_engine.create_request(
            image_id=scene.scene_id,
            scene_id=scene.scene_id,
            prompt=prompt,
            output_directory=str(OUTPUT_DIR),
        )

        print(f"Generating {index}/{len(TEST_SCENES)}")
        print(f"Text: {scene.text_overlay}")
        print()

        print("Prompt:")
        print(prompt)
        print()

        result = image_engine.generate(request)

        if result.status != "completed":
            raise RuntimeError(
                f"Image generation failed for "
                f"{scene.scene_id}: {result.error_message}"
            )

        print(f"Generated: {result.file_path}")
        print("-" * 60)

    print()
    print("EDITORIAL TEXT TEST COMPLETE")
    print()
    print(
        "Open the generated images and verify that the requested "
        "editorial text is rendered inside each illustration."
    )


if __name__ == "__main__":
    main()