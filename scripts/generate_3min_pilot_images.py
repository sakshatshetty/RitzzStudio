from __future__ import annotations

import sys
from pathlib import Path

# ============================================================================
# PROJECT PATH
# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================================
# IMPORTS
# ============================================================================

from modules.image.batch import ImageBatchEngine
from modules.image.character_profile import load_character_profile
from modules.image.engine import ImageEngine
from modules.image.providers.openai import OpenAIImageProvider
from modules.image.prompt_builder import ImagePromptBuilder
from modules.storyboard.models import Storyboard


# ============================================================================
# PROJECT CONFIGURATION
# ============================================================================

PROJECT_ID = (
    "20260820_001_why_do_pirates_wear_eye_patches"
)

PROJECT_DIRECTORY = (
    PROJECT_ROOT
    / "projects"
    / PROJECT_ID
)

PILOT_DIRECTORY = (
    PROJECT_DIRECTORY
    / "pilot_3min"
)

STORYBOARD_FILE = (
    PILOT_DIRECTORY
    / "storyboard_dynamic.json"
)

IMAGE_DIRECTORY = (
    PILOT_DIRECTORY
    / "images"
)

MANIFEST_FILE = (
    IMAGE_DIRECTORY
    / "image_manifest.json"
)

EXPECTED_IMAGE_COUNT = 83

TARGET_DURATION_SECONDS = 180.0

MIN_SCENE_DURATION = 1.0
MAX_SCENE_DURATION = 3.0

MAX_EDITORIAL_WORDS = 1
MAX_EDITORIAL_CHARACTERS = 20


# ============================================================================
# STORYBOARD LOADING
# ============================================================================

def load_storyboard() -> Storyboard:
    """
    Load and validate the 3-minute dynamic pilot storyboard.
    """

    if not STORYBOARD_FILE.exists():
        raise FileNotFoundError(
            f"Pilot storyboard not found: "
            f"{STORYBOARD_FILE}"
        )

    return Storyboard.model_validate_json(
        STORYBOARD_FILE.read_text(
            encoding="utf-8"
        )
    )


# ============================================================================
# STORYBOARD PREFLIGHT
# ============================================================================

def validate_storyboard(
    storyboard: Storyboard,
) -> None:
    """
    Validate the dynamic pilot storyboard before making any image API calls.
    """

    scene_count = len(
        storyboard.scenes
    )

    # ----------------------------------------------------------------------
    # Scene count
    # ----------------------------------------------------------------------

    if scene_count != EXPECTED_IMAGE_COUNT:
        raise ValueError(
            "Pilot storyboard must contain "
            f"{EXPECTED_IMAGE_COUNT} scenes, "
            f"but found {scene_count}."
        )

    # ----------------------------------------------------------------------
    # Target duration
    # ----------------------------------------------------------------------

    if abs(
        storyboard.target_duration_seconds
        - TARGET_DURATION_SECONDS
    ) > 0.001:
        raise ValueError(
            "Pilot storyboard target duration mismatch. "
            f"Expected {TARGET_DURATION_SECONDS}s, "
            f"found {storyboard.target_duration_seconds}s."
        )

    actual_total_duration = sum(
        scene.duration_seconds
        for scene in storyboard.scenes
    )

    if abs(
        actual_total_duration
        - TARGET_DURATION_SECONDS
    ) > 0.001:
        raise ValueError(
            "Pilot storyboard duration mismatch. "
            f"Expected {TARGET_DURATION_SECONDS:.3f}s, "
            f"found {actual_total_duration:.3f}s."
        )

    # ----------------------------------------------------------------------
    # Scene IDs
    # ----------------------------------------------------------------------

    scene_ids = [
        scene.scene_id
        for scene in storyboard.scenes
    ]

    if len(scene_ids) != len(
        set(scene_ids)
    ):
        raise ValueError(
            "Pilot storyboard contains duplicate scene IDs."
        )

    # ----------------------------------------------------------------------
    # Timeline validation
    # ----------------------------------------------------------------------

    previous_end = 0.0

    for index, scene in enumerate(
        storyboard.scenes,
        start=1,
    ):
        expected_id = (
            f"scene_{index:03d}"
        )

        if scene.scene_id != expected_id:
            raise ValueError(
                "Pilot storyboard scene ordering mismatch. "
                f"Expected {expected_id}, "
                f"found {scene.scene_id}."
            )

        # --------------------------------------------------------------
        # Duration
        # --------------------------------------------------------------

        if not (
            MIN_SCENE_DURATION
            <= scene.duration_seconds
            <= MAX_SCENE_DURATION
        ):
            raise ValueError(
                f"{scene.scene_id} duration "
                f"{scene.duration_seconds:.3f}s is outside "
                f"the allowed range "
                f"{MIN_SCENE_DURATION:.1f}s–"
                f"{MAX_SCENE_DURATION:.1f}s."
            )

        # --------------------------------------------------------------
        # Sequential timeline
        # --------------------------------------------------------------

        if abs(
            scene.start_seconds
            - previous_end
        ) > 0.001:
            raise ValueError(
                f"Timeline gap/overlap detected at "
                f"{scene.scene_id}."
            )

        previous_end = (
            scene.start_seconds
            + scene.duration_seconds
        )

        # --------------------------------------------------------------
        # Narration
        # --------------------------------------------------------------

        if not scene.narration.strip():
            raise ValueError(
                f"{scene.scene_id} has empty narration."
            )

        # --------------------------------------------------------------
        # Visual description
        # --------------------------------------------------------------

        if not scene.visual_description.strip():
            raise ValueError(
                f"{scene.scene_id} has empty "
                "visual description."
            )

        # --------------------------------------------------------------
        # Image prompt
        # --------------------------------------------------------------

        if not scene.image_prompt.strip():
            raise ValueError(
                f"{scene.scene_id} has empty image prompt."
            )

        # --------------------------------------------------------------
        # Camera
        # --------------------------------------------------------------

        if scene.camera_motion != "static":
            raise ValueError(
                f"{scene.scene_id} must use a static camera."
            )

        # --------------------------------------------------------------
        # Transition
        # --------------------------------------------------------------

        if scene.transition != "cut":
            raise ValueError(
                f"{scene.scene_id} must use a hard cut."
            )

        # --------------------------------------------------------------
        # Editorial text
        # --------------------------------------------------------------

        if scene.text_overlay.strip():
            editorial = scene.text_overlay.strip()

            editorial_words = (
                editorial.split()
            )

            if len(editorial_words) != MAX_EDITORIAL_WORDS:
                raise ValueError(
                    f"{scene.scene_id} editorial text must "
                    "contain exactly one word. "
                    f"Found: {editorial!r}"
                )

            if len(editorial) > MAX_EDITORIAL_CHARACTERS:
                raise ValueError(
                    f"{scene.scene_id} editorial text is too long: "
                    f"{editorial!r}"
                )

            if editorial != editorial.upper():
                raise ValueError(
                    f"{scene.scene_id} editorial text must "
                    f"be uppercase: {editorial!r}"
                )

    # ----------------------------------------------------------------------
    # Final timeline endpoint
    # ----------------------------------------------------------------------

    if abs(
        previous_end
        - TARGET_DURATION_SECONDS
    ) > 0.001:
        raise ValueError(
            "Pilot storyboard final endpoint mismatch. "
            f"Expected {TARGET_DURATION_SECONDS:.3f}s, "
            f"found {previous_end:.3f}s."
        )

    # ----------------------------------------------------------------------
    # Preflight output
    # ----------------------------------------------------------------------

    editorial_scenes = [
        scene
        for scene in storyboard.scenes
        if scene.text_overlay.strip()
    ]

    durations = [
        scene.duration_seconds
        for scene in storyboard.scenes
    ]

    print()
    print(
        "RITZZ — 3-MINUTE PILOT IMAGE PREFLIGHT"
    )
    print(
        "---------------------------------------"
    )
    print(
        f"Topic: {storyboard.topic}"
    )
    print(
        f"Scenes: {scene_count}"
    )
    print(
        f"Target duration: "
        f"{TARGET_DURATION_SECONDS:.3f}s"
    )
    print(
        f"Actual storyboard duration: "
        f"{actual_total_duration:.3f}s"
    )
    print(
        f"Minimum scene: "
        f"{min(durations):.3f}s"
    )
    print(
        f"Maximum scene: "
        f"{max(durations):.3f}s"
    )
    print(
        f"Editorial scenes: "
        f"{len(editorial_scenes)}"
    )
    print(
        "Camera: STATIC"
    )
    print(
        "Transitions: HARD CUT"
    )
    print(
        "Editorial text: ONE WORD"
    )
    print(
        "Storyboard validation: PASS"
    )
    print()


# ============================================================================
# IMAGE GENERATION
# ============================================================================

def main() -> int:
    """
    Generate the 3-minute pilot images.
    """

    try:
        # --------------------------------------------------------------
        # Load storyboard
        # --------------------------------------------------------------

        storyboard = load_storyboard()

        # --------------------------------------------------------------
        # Preflight
        # --------------------------------------------------------------

        validate_storyboard(
            storyboard
        )

        # --------------------------------------------------------------
        # Prepare output directory
        # --------------------------------------------------------------

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
            image_engine=image_engine,
            prompt_builder=ImagePromptBuilder(
                character_profile=load_character_profile(
                    PROJECT_DIRECTORY
                )
            ),
        )

        print(
            "Starting 3-minute pilot image generation..."
        )

        print(
            f"Storyboard: "
            f"{STORYBOARD_FILE}"
        )

        print(
            f"Output directory: "
            f"{IMAGE_DIRECTORY}"
        )

        print(
            f"Expected images: "
            f"{EXPECTED_IMAGE_COUNT}"
        )

        print()

        # --------------------------------------------------------------
        # Generate images
        # --------------------------------------------------------------

        assets = batch_engine.generate(
            storyboard=storyboard,
            output_directory=IMAGE_DIRECTORY,
        )

        # --------------------------------------------------------------
        # Save manifest
        # --------------------------------------------------------------

        batch_engine.save_manifest(
            assets,
            MANIFEST_FILE,
        )

        # --------------------------------------------------------------
        # Categorize results
        # --------------------------------------------------------------

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

        pending = [
            asset
            for asset in assets
            if asset.status not in {
                "completed",
                "failed",
            }
        ]

        # --------------------------------------------------------------
        # Result
        # --------------------------------------------------------------

        print()
        print(
            "RITZZ — 3-MINUTE PILOT IMAGE RESULT"
        )
        print(
            "------------------------------------"
        )

        print(
            f"Expected images: "
            f"{EXPECTED_IMAGE_COUNT}"
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
            f"Other/pending: "
            f"{len(pending)}"
        )

        print(
            f"Manifest: "
            f"{MANIFEST_FILE}"
        )

        # --------------------------------------------------------------
        # Failed image details
        # --------------------------------------------------------------

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

        # --------------------------------------------------------------
        # Final status
        # --------------------------------------------------------------

        if failed:
            print()
            print(
                "Pilot image generation did not "
                "fully complete."
            )

            return 1

        if len(completed) != EXPECTED_IMAGE_COUNT:
            print()
            print(
                "Pilot image validation failed: "
                f"expected {EXPECTED_IMAGE_COUNT} "
                f"completed images, "
                f"found {len(completed)}."
            )

            return 1

        print()
        print(
            f"All {EXPECTED_IMAGE_COUNT} pilot "
            "images generated successfully."
        )

        print()
        print(
            "Next step: 3-minute pilot render."
        )

        return 0

    except Exception as exc:
        print()
        print(
            "3-minute pilot image generation failed."
        )

        print(
            f"Error: {exc}"
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )