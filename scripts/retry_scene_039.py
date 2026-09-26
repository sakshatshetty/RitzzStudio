import sys
from pathlib import Path

# Ensure project root is available.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from modules.image.batch import ImageBatchEngine
from modules.image.character_profile import load_character_profile
from modules.image.engine import ImageEngine
from modules.image.providers.openai import OpenAIImageProvider
from modules.image.prompt_builder import ImagePromptBuilder
from modules.storyboard.engine import StoryboardEngine


PROJECT_ID = (
    "20260820_001_why_do_pirates_wear_eye_patches"
)

PROJECT_DIRECTORY = (
    PROJECT_ROOT
    / "projects"
    / PROJECT_ID
)

STORYBOARD_FILE = (
    PROJECT_DIRECTORY
    / "storyboard"
    / "storyboard.json"
)

IMAGE_DIRECTORY = (
    PROJECT_DIRECTORY
    / "images"
)

MANIFEST_FILE = (
    IMAGE_DIRECTORY
    / "image_manifest.json"
)

SCENE_ID = "scene_039"


def main() -> int:
    try:
        print()
        print(
            "RITZZ — RETRY SCENE 039"
        )
        print(
            "------------------------"
        )

        # -------------------------------------------------------------
        # Load storyboard
        # -------------------------------------------------------------

        storyboard_engine = StoryboardEngine()

        storyboard = (
            storyboard_engine.load_storyboard(
                STORYBOARD_FILE
            )
        )

        scene = next(
            (
                item
                for item in storyboard.scenes
                if item.scene_id == SCENE_ID
            ),
            None,
        )

        if scene is None:
            raise ValueError(
                f"{SCENE_ID} was not found in storyboard."
            )

        # -------------------------------------------------------------
        # Update only Scene 039 visual information
        # -------------------------------------------------------------

        scene.visual_description = (
            "Simple hand-drawn stick-man explainer scene "
            "showing a pirate calmly wearing and adjusting "
            "an eye patch with one hand. A closed first-aid "
            "kit and a folded clean cloth sit nearby, "
            "suggesting protection and recovery without "
            "showing any wound or physical harm."
        )

        scene.character_action = (
            "The pirate gently adjusts the eye patch "
            "and gestures toward the clean cloth and "
            "closed first-aid kit."
        )

        scene.background = (
            "Simple wooden ship deck with open sea "
            "and a clean uncluttered background."
        )

        scene.props = [
            "eye patch",
            "closed first-aid kit",
            "folded cloth",
        ]

        scene.image_prompt = (
            "Ritzz visual style: simple hand-drawn 2D "
            "stick-man explainer illustration, clean "
            "composition, strong black outlines, minimal "
            "background, readable visual storytelling, "
            "consistent character design. Scene topic: "
            "The Real Reason a Pirate Might Wear One. "
            "Visual idea: a pirate calmly wearing and "
            "adjusting an eye patch on a simple ship deck, "
            "with a closed first-aid kit and folded cloth "
            "nearby to suggest protection and recovery. "
            "No wounds, blood, pain, or depiction of "
            "physical harm. No photorealism, no 3D rendering, "
            "no unnecessary visual clutter."
        )

        # -------------------------------------------------------------
        # Save updated storyboard
        # -------------------------------------------------------------

        storyboard_engine.save_storyboard(
            storyboard,
            STORYBOARD_FILE,
        )

        print(
            "Storyboard Scene 039 updated."
        )

        # -------------------------------------------------------------
        # Create a temporary one-scene storyboard
        # -------------------------------------------------------------

        single_scene_storyboard = (
            storyboard.model_copy(
                update={
                    "scenes": [
                        scene
                    ]
                }
            )
        )

        # -------------------------------------------------------------
        # Initialize image engine
        # -------------------------------------------------------------

        provider = OpenAIImageProvider()

        image_engine = ImageEngine(
            provider=provider
        )

        batch_engine = ImageBatchEngine(
            image_engine=image_engine,
            prompt_builder=ImagePromptBuilder(
                character_profile=load_character_profile(
                    PROJECT_DIRECTORY
                )
            ),
        )

        # -------------------------------------------------------------
        # Generate only Scene 039
        # -------------------------------------------------------------

        requests = batch_engine.create_requests(
            storyboard=single_scene_storyboard,
            output_directory=IMAGE_DIRECTORY,
        )

        if len(requests) != 1:
            raise ValueError(
                "Expected exactly one image request."
            )

        print(
            "Generating Scene 039..."
        )

        asset = (
            image_engine.generate_asset(
                requests[0]
            )
        )

        if asset.status != "completed":
            raise RuntimeError(
                "Scene 039 generation failed: "
                f"{asset.error_message}"
            )

        print(
            f"Scene 039 generated successfully: "
            f"{asset.file_path}"
        )

        # -------------------------------------------------------------
        # Update existing manifest
        # -------------------------------------------------------------

        if MANIFEST_FILE.exists():
            assets = (
                batch_engine.load_manifest(
                    MANIFEST_FILE
                )
            )

            updated = False

            for index, existing_asset in enumerate(
                assets
            ):
                if existing_asset.image_id == asset.image_id:
                    assets[index] = asset
                    updated = True
                    break

            if not updated:
                assets.append(
                    asset
                )

        else:
            assets = [asset]

        batch_engine.save_manifest(
            assets,
            MANIFEST_FILE,
        )

        print(
            "Image manifest updated."
        )

        print()
        print(
            "Scene 039 retry completed successfully."
        )

        return 0

    except Exception as exc:
        print()
        print(
            "Scene 039 retry failed."
        )
        print(
            f"Error: {exc}"
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )