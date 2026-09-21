import sys
from pathlib import Path

# Ensure project root is available when the script is
# launched directly from the scripts directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from modules.image.batch import ImageBatchEngine
from modules.image.engine import ImageEngine
from modules.image.providers.openai import OpenAIImageProvider
from modules.storyboard.models import Storyboard


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

EXPECTED_IMAGE_COUNT = 96


def load_storyboard() -> Storyboard:
    """
    Load and validate the production storyboard.
    """

    if not STORYBOARD_FILE.exists():
        raise FileNotFoundError(
            f"Storyboard not found: {STORYBOARD_FILE}"
        )

    return Storyboard.model_validate_json(
        STORYBOARD_FILE.read_text(
            encoding="utf-8"
        )
    )


def validate_storyboard(
    storyboard: Storyboard,
) -> None:
    """
    Perform production preflight validation before
    image-generation API calls are made.
    """

    scene_count = len(
        storyboard.scenes
    )

    if scene_count != EXPECTED_IMAGE_COUNT:
        raise ValueError(
            "Production storyboard must contain "
            f"{EXPECTED_IMAGE_COUNT} scenes, "
            f"but found {scene_count}."
        )

    scene_ids = [
        scene.scene_id
        for scene in storyboard.scenes
    ]

    if len(scene_ids) != len(
        set(scene_ids)
    ):
        raise ValueError(
            "Storyboard contains duplicate scene IDs."
        )

    for index, scene in enumerate(
        storyboard.scenes,
        start=1,
    ):
        expected_id = (
            f"scene_{index:03d}"
        )

        if scene.scene_id != expected_id:
            raise ValueError(
                "Storyboard scene ordering mismatch. "
                f"Expected {expected_id}, "
                f"found {scene.scene_id}."
            )

        if not scene.narration.strip():
            raise ValueError(
                f"{scene.scene_id} has empty narration."
            )

        if not scene.visual_description.strip():
            raise ValueError(
                f"{scene.scene_id} has empty "
                "visual description."
            )

        if not scene.image_prompt.strip():
            raise ValueError(
                f"{scene.scene_id} has empty "
                "image prompt."
            )

    print()
    print(
        "RITZZ — PRODUCTION IMAGE PREFLIGHT"
    )
    print(
        "------------------------------------"
    )
    print(
        f"Topic: {storyboard.topic}"
    )
    print(
        f"Scenes: {scene_count}"
    )
    print(
        f"Target duration: "
        f"{storyboard.target_duration_seconds}s"
    )
    print(
        f"Target scene duration: "
        f"{storyboard.target_scene_duration_seconds}s"
    )
    print(
        "Scene validation: PASS"
    )
    print()


def main() -> int:
    """
    Generate all production images.
    """

    try:
        storyboard = load_storyboard()

        validate_storyboard(
            storyboard
        )

        IMAGE_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        print(
            "Initializing OpenAI image provider..."
        )

        provider = OpenAIImageProvider()

        image_engine = ImageEngine(
            provider=provider
        )

        batch_engine = ImageBatchEngine(
            image_engine=image_engine
        )

        print(
            "Starting production image generation..."
        )

        print(
            f"Output directory: "
            f"{IMAGE_DIRECTORY}"
        )

        print()

        assets = batch_engine.generate(
            storyboard=storyboard,
            output_directory=IMAGE_DIRECTORY,
        )

        batch_engine.save_manifest(
            assets,
            MANIFEST_FILE,
        )

        completed = [
            asset
            for asset in assets
            if asset.status == "completed"
        ]

        failed = [
            asset
            for asset in assets
            if asset.status == "failed"
        ]

        print()
        print(
            "RITZZ — PRODUCTION IMAGE RESULT"
        )
        print(
            "--------------------------------"
        )

        print(
            f"Expected images: "
            f"{len(storyboard.scenes)}"
        )

        print(
            f"Completed: "
            f"{len(completed)}"
        )

        print(
            f"Failed: "
            f"{len(failed)}"
        )

        print(
            f"Manifest: "
            f"{MANIFEST_FILE}"
        )

        if failed:
            print()
            print(
                "Failed images:"
            )

            for asset in failed:
                print(
                    f"  {asset.image_id}: "
                    f"{asset.error_message}"
                )

            print()
            print(
                "Production image generation "
                "did not fully complete."
            )

            return 1

        if len(completed) != EXPECTED_IMAGE_COUNT:
            print()
            print(
                "Production validation failed: "
                f"expected {EXPECTED_IMAGE_COUNT} "
                "completed images."
            )

            return 1

        print()
        print(
            f"All {EXPECTED_IMAGE_COUNT} production "
            "images generated successfully."
        )

        return 0

    except Exception as exc:
        print()
        print(
            "Production image generation failed."
        )

        print(
            f"Error: {exc}"
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )