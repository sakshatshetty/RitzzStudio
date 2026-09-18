from pathlib import Path
import sys


# =============================================================
# PROJECT ROOT
# =============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


# =============================================================
# IMPORTS
# =============================================================

from modules.image.engine import ImageEngine
from modules.image.prompt_builder import ImagePromptBuilder
from modules.image.providers.openai import OpenAIImageProvider
from modules.storyboard.engine import StoryboardEngine
from modules.storyboard.models import Storyboard


# =============================================================
# PROJECT PATHS
# =============================================================

PROJECT_DIR = (
    PROJECT_ROOT
    / "projects"
    / "20260820_001_why_do_pirates_wear_eye_patches"
)

SCRIPT_FILE = (
    PROJECT_DIR
    / "script"
    / "script.json"
)

OUTPUT_DIR = (
    PROJECT_DIR
    / "images"
    / "consistency_test_v2"
)


# =============================================================
# VIDEO CHARACTER PROFILE
# =============================================================

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


# =============================================================
# SCENE SELECTION
# =============================================================

def select_test_scenes(
    storyboard: Storyboard,
):
    """
    Select six representative scenes.

    The selection intentionally includes:
    - character introduction
    - ship/deck scene
    - eye-patch scene
    - darker scene
    - light/dark scene
    - editorial-text scene
    """

    if not storyboard.scenes:
        raise ValueError(
            "Storyboard contains no scenes."
        )

    selected = []
    used_ids: set[str] = set()

    # ---------------------------------------------------------
    # Helper
    # ---------------------------------------------------------

    def add_scene(scene):
        if scene.scene_id in used_ids:
            return False

        selected.append(scene)
        used_ids.add(scene.scene_id)

        return True

    # ---------------------------------------------------------
    # 1. Character introduction
    # ---------------------------------------------------------

    add_scene(
        storyboard.scenes[0]
    )

    # ---------------------------------------------------------
    # Keyword-based scene selection
    # ---------------------------------------------------------

    keyword_groups = [
        (
            "ship",
            "deck",
        ),
        (
            "eye",
            "patch",
        ),
        (
            "dark",
            "below",
            "interior",
        ),
        (
            "sun",
            "light",
            "bright",
        ),
    ]

    for keywords in keyword_groups:

        for scene in storyboard.scenes:

            if scene.scene_id in used_ids:
                continue

            searchable_text = " ".join(
                [
                    scene.visual_description,
                    scene.character_action,
                    scene.background,
                    " ".join(scene.props),
                    scene.narration,
                ]
            ).lower()

            if any(
                keyword in searchable_text
                for keyword in keywords
            ):
                add_scene(scene)
                break

        if len(selected) >= 5:
            break

    # ---------------------------------------------------------
    # Editorial-text scene
    # ---------------------------------------------------------

    editorial_scene = next(
        (
            scene
            for scene in storyboard.scenes
            if scene.scene_id not in used_ids
            and scene.text_overlay.strip()
        ),
        None,
    )

    if editorial_scene is not None:
        add_scene(
            editorial_scene
        )

    # ---------------------------------------------------------
    # Fallback
    # ---------------------------------------------------------

    if len(selected) < 6:

        for scene in storyboard.scenes:

            if scene.scene_id in used_ids:
                continue

            add_scene(scene)

            if len(selected) == 6:
                break

    return selected[:6]


# =============================================================
# MAIN
# =============================================================

def main() -> None:

    print()
    print("=" * 70)
    print("RITZZ - REAL IMAGE CONSISTENCY TEST V2")
    print("=" * 70)
    print()

    print(
        f"Project root: {PROJECT_ROOT}"
    )

    print(
        f"Script:       {SCRIPT_FILE}"
    )

    print(
        f"Output:       {OUTPUT_DIR}"
    )

    print()

    # ---------------------------------------------------------
    # Validate script
    # ---------------------------------------------------------

    if not SCRIPT_FILE.exists():
        raise FileNotFoundError(
            f"Script not found: {SCRIPT_FILE}"
        )

    # ---------------------------------------------------------
    # Create storyboard
    # ---------------------------------------------------------

    print(
        "Creating storyboard from script..."
    )

    storyboard_engine = StoryboardEngine(
        target_scene_duration_seconds=5.0
    )

    storyboard = (
        storyboard_engine.create_storyboard(
            SCRIPT_FILE
        )
    )

    print(
        f"Created storyboard with "
        f"{len(storyboard.scenes)} scenes."
    )

    print(
        f"Target duration: "
        f"{storyboard.target_duration_seconds}s"
    )

    print(
        f"Scene duration: "
        f"{storyboard.target_scene_duration_seconds}s"
    )

    print()

    # ---------------------------------------------------------
    # Select scenes
    # ---------------------------------------------------------

    scenes = select_test_scenes(
        storyboard
    )

    if len(scenes) < 6:
        raise ValueError(
            f"Could only select "
            f"{len(scenes)} test scenes. "
            "Six are required."
        )

    # ---------------------------------------------------------
    # Prompt builder
    # ---------------------------------------------------------

    prompt_builder = ImagePromptBuilder(
        character_profile=(
            PIRATE_CHARACTER_PROFILE
        )
    )

    print(
        "Character profile:"
    )

    print(
        f"  {PIRATE_CHARACTER_PROFILE}"
    )

    print()

    # ---------------------------------------------------------
    # Display selected scenes
    # ---------------------------------------------------------

    print(
        "Selected scenes:"
    )

    print()

    for index, scene in enumerate(
        scenes,
        start=1,
    ):

        prompt = prompt_builder.build(
            scene
        )

        print(
            f"{index}. {scene.scene_id} "
            f"({scene.start_seconds:.1f}s)"
        )

        print(
            f"   Visual: "
            f"{scene.visual_description}"
        )

        print(
            f"   Action: "
            f"{scene.character_action}"
        )

        print(
            f"   Background: "
            f"{scene.background}"
        )

        print(
            f"   Text: "
            f"{scene.text_overlay or '[NONE]'}"
        )

        print(
            f"   Camera: "
            f"{scene.camera_motion}"
        )

        print(
            "   Generated prompt:"
        )

        print(
            f"   {prompt}"
        )

        print()

    # ---------------------------------------------------------
    # Initialize OpenAI
    # ---------------------------------------------------------

    print(
        "Initializing OpenAI image provider..."
    )

    provider = OpenAIImageProvider()

    image_engine = ImageEngine(
        provider
    )

    # ---------------------------------------------------------
    # Output directory
    # ---------------------------------------------------------

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()

    print(
        "Generating 6 real images..."
    )

    print()

    results = []

    # ---------------------------------------------------------
    # Generate
    # ---------------------------------------------------------

    for index, scene in enumerate(
        scenes,
        start=1,
    ):

        print(
            f"[{index}/6] Generating "
            f"{scene.scene_id}..."
        )

        # IMPORTANT:
        # Use ImagePromptBuilder instead of
        # scene.image_prompt.
        prompt = prompt_builder.build(
            scene
        )

        request = (
            image_engine.create_request(
                image_id=(
                    f"consistency_v2_{index:03d}"
                ),
                scene_id=scene.scene_id,
                prompt=prompt,
                output_directory=OUTPUT_DIR,
            )
        )

        print(
            f"      Image ID: "
            f"{request.image_id}"
        )

        print(
            f"      Size: "
            f"{request.width}x"
            f"{request.height}"
        )

        result = image_engine.generate(
            request
        )

        results.append(
            result
        )

        if result.status == "completed":

            print(
                "      SUCCESS"
            )

            print(
                f"      File: "
                f"{result.file_path}"
            )

        else:

            print(
                "      FAILED"
            )

            print(
                f"      Error: "
                f"{result.error_message}"
            )

        print()

    # ---------------------------------------------------------
    # Results
    # ---------------------------------------------------------

    print("=" * 70)
    print("RESULT")
    print("=" * 70)

    successful = sum(
        1
        for result in results
        if result.status == "completed"
    )

    failed = sum(
        1
        for result in results
        if result.status == "failed"
    )

    print(
        f"Successful: {successful}/6"
    )

    print(
        f"Failed:     {failed}/6"
    )

    print()

    # ---------------------------------------------------------
    # Generated files
    # ---------------------------------------------------------

    if successful:

        print(
            "Generated files:"
        )

        for result in results:

            if result.file_path:

                print(
                    f"  {result.file_path}"
                )

    print()

    # ---------------------------------------------------------
    # Final status
    # ---------------------------------------------------------

    if failed:

        raise RuntimeError(
            "One or more image generations failed."
        )

    print(
        "Milestone 18A image generation "
        "test completed successfully."
    )

    print()

    print(
        "IMPORTANT:"
    )

    print(
        "Do not generate the full 96-image batch yet."
    )

    print(
        "First inspect the six V2 images for "
        "simplicity, character consistency, "
        "and editorial-text quality."
    )

    print()


if __name__ == "__main__":
    main()