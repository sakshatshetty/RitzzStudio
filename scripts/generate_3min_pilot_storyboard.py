import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from modules.storyboard.dynamic_engine import (
    DynamicStoryboardEngine,
)

from modules.storyboard.editorial_planner import (
    OpenAIEditorialTextPlanner,
)

from modules.storyboard.engine import (
    StoryboardEngine,
)


PROJECT_ID = (
    "20260820_001_why_do_pirates_wear_eye_patches"
)

PROJECT_DIRECTORY = (
    PROJECT_ROOT
    / "projects"
    / PROJECT_ID
)

SOURCE_STORYBOARD_FILE = (
    PROJECT_DIRECTORY
    / "storyboard"
    / "storyboard.json"
)

PILOT_DIRECTORY = (
    PROJECT_DIRECTORY
    / "pilot_3min"
)

PILOT_STORYBOARD_FILE = (
    PILOT_DIRECTORY
    / "storyboard_dynamic.json"
)

TARGET_DURATION_SECONDS = 180.0


def main() -> int:
    try:
        print()
        print(
            "RITZZ — 3-MINUTE DYNAMIC STORYBOARD"
        )
        print(
            "===================================="
        )
        print()

        if not SOURCE_STORYBOARD_FILE.exists():
            raise FileNotFoundError(
                "Source storyboard not found: "
                f"{SOURCE_STORYBOARD_FILE}"
            )

        source_engine = StoryboardEngine()

        source_storyboard = (
            source_engine.load_storyboard(
                SOURCE_STORYBOARD_FILE
            )
        )

        print(
            f"Source scenes: "
            f"{len(source_storyboard.scenes)}"
        )

        print(
            f"Target pilot duration: "
            f"{TARGET_DURATION_SECONDS}s"
        )

        print()

        editorial_planner = (
            OpenAIEditorialTextPlanner()
        )

        print(
            f"Editorial planner model: "
            f"{editorial_planner.model}"
        )

        print(
            "Editorial cadence: EVERY 3-4 SCENES"
        )

        print(
            "Editorial wording: CONTEXT-AWARE LLM"
        )

        print()

        engine = DynamicStoryboardEngine(
            editorial_planner=(
                editorial_planner
            )
        )

        pilot = (
            engine.create_pilot_storyboard(
                source_storyboard,
                target_duration_seconds=(
                    TARGET_DURATION_SECONDS
                ),
            )
        )

        PILOT_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        engine.save_storyboard(
            pilot,
            PILOT_STORYBOARD_FILE,
        )

        editorial_scenes = [
            scene
            for scene in pilot.scenes
            if scene.text_overlay.strip()
        ]

        durations = [
            scene.duration_seconds
            for scene in pilot.scenes
        ]

        print(
            f"Pilot scenes: "
            f"{len(pilot.scenes)}"
        )

        print(
            f"Pilot duration: "
            f"{pilot.total_scene_duration_seconds:.3f}s"
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
            f"Editorial text scenes: "
            f"{len(editorial_scenes)}"
        )

        print(
            "Camera motion: STATIC"
        )

        print(
            "Transitions: HARD CUT"
        )

        print()

        print(
            "EDITORIAL CALLOUTS"
        )

        print(
            "------------------"
        )

        for scene in editorial_scenes:
            print(
                f"{scene.scene_id:<12} "
                f"{scene.duration_seconds:>5.3f}s  "
                f"{scene.text_overlay}"
            )

        print()

        print(
            f"Saved: {PILOT_STORYBOARD_FILE}"
        )

        print()

        print(
            "Production 3-minute storyboard created."
        )

        return 0

    except Exception as exc:
        print()
        print(
            "3-minute storyboard generation failed."
        )

        print(
            f"Error: {exc}"
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )