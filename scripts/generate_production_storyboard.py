import sys
from pathlib import Path

# Ensure project root is available when the script is
# launched directly from the scripts directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from modules.storyboard.engine import StoryboardEngine


PROJECT_ID = (
    "20260820_001_why_do_pirates_wear_eye_patches"
)

PROJECT_DIRECTORY = (
    PROJECT_ROOT
    / "projects"
    / PROJECT_ID
)

SCRIPT_FILE = (
    PROJECT_DIRECTORY
    / "script"
    / "script.json"
)

STORYBOARD_DIRECTORY = (
    PROJECT_DIRECTORY
    / "storyboard"
)

STORYBOARD_FILE = (
    STORYBOARD_DIRECTORY
    / "storyboard.json"
)

EXPECTED_SCENE_COUNT = 96


def validate_production_storyboard(
    storyboard,
) -> None:
    """
    Validate the production storyboard before
    image generation begins.
    """

    scene_count = len(
        storyboard.scenes
    )

    if scene_count != EXPECTED_SCENE_COUNT:
        raise ValueError(
            "Expected "
            f"{EXPECTED_SCENE_COUNT} storyboard scenes, "
            f"but generated {scene_count}."
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

    if abs(
        storyboard.total_scene_duration_seconds
        - storyboard.target_duration_seconds
    ) > 0.01:
        raise ValueError(
            "Storyboard total scene duration does not "
            "match target duration."
        )

    print(
        f"Scene count: {scene_count}"
    )

    print(
        "Scene IDs: PASS"
    )

    print(
        "Narration validation: PASS"
    )

    print(
        "Visual description validation: PASS"
    )

    print(
        "Image prompt validation: PASS"
    )

    print(
        "Storyboard duration validation: PASS"
    )


def main() -> int:
    """
    Generate and save the production storyboard.
    """

    try:
        if not SCRIPT_FILE.exists():
            raise FileNotFoundError(
                f"Script not found: {SCRIPT_FILE}"
            )

        STORYBOARD_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        print()
        print(
            "RITZZ — PRODUCTION STORYBOARD GENERATION"
        )
        print(
            "-----------------------------------------"
        )
        print(
            f"Script: {SCRIPT_FILE}"
        )
        print(
            f"Output: {STORYBOARD_FILE}"
        )
        print()

        engine = StoryboardEngine(
            target_scene_duration_seconds=5.0
        )

        storyboard = engine.create_storyboard(
            script_file=SCRIPT_FILE,
            output_file=STORYBOARD_FILE,
        )

        print(
            f"Topic: {storyboard.topic}"
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
            f"Generated scenes: "
            f"{len(storyboard.scenes)}"
        )

        print()

        validate_production_storyboard(
            storyboard
        )

        print()
        print(
            "Storyboard saved successfully:"
        )
        print(
            STORYBOARD_FILE
        )

        print()
        print(
            "Production storyboard generation passed."
        )

        return 0

    except Exception as exc:
        print()
        print(
            "Production storyboard generation failed."
        )
        print(
            f"Error: {exc}"
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )