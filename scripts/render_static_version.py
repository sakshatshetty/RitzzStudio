import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from modules.video.engine import VideoAssemblyEngine
from modules.video.motion_models import (
    MotionInstruction,
    VideoMotionPlan,
)
from modules.video.render_engine import (
    FFmpegVideoRenderer,
)


PROJECT_ID = (
    "20260820_001_why_do_pirates_wear_eye_patches"
)

PROJECT_DIRECTORY = (
    PROJECT_ROOT / "projects" / PROJECT_ID
)

SYNCED_PLAN_FILE = (
    PROJECT_DIRECTORY
    / "video"
    / "synced_video_plan.json"
)

AUDIO_FILE = (
    PROJECT_DIRECTORY
    / "voice"
    / "narration.mp3"
)

OUTPUT_FILE = (
    PROJECT_DIRECTORY
    / "video"
    / "pirates_eye_patch_static.mp4"
)


def main() -> int:
    try:
        print()
        print(
            "RITZZ — STATIC VIDEO RENDER"
        )
        print(
            "============================"
        )
        print()

        # ---------------------------------------------------------
        # Load synchronized plan
        # ---------------------------------------------------------

        if not SYNCED_PLAN_FILE.exists():
            raise FileNotFoundError(
                f"Synchronized plan not found: "
                f"{SYNCED_PLAN_FILE}"
            )

        if not AUDIO_FILE.exists():
            raise FileNotFoundError(
                f"Audio file not found: "
                f"{AUDIO_FILE}"
            )

        assembly_plan = (
            VideoAssemblyEngine.load_plan(
                SYNCED_PLAN_FILE
            )
        )

        if not assembly_plan.clips:
            raise ValueError(
                "Synchronized plan contains no clips."
            )

        print(
            f"Scenes: {len(assembly_plan.clips)}"
        )

        print(
            f"Duration: "
            f"{assembly_plan.total_duration_seconds:.3f}s"
        )

        print(
            f"Resolution: "
            f"{assembly_plan.width}x"
            f"{assembly_plan.height}"
        )

        print()

        # ---------------------------------------------------------
        # Create completely static motion plan
        # ---------------------------------------------------------

        instructions: list[
            MotionInstruction
        ] = []

        for clip in assembly_plan.clips:
            instructions.append(
                MotionInstruction(
                    scene_id=clip.scene_id,
                    start_seconds=clip.start_seconds,
                    duration_seconds=clip.duration_seconds,
                    motion="static",
                    zoom_start=1.0,
                    zoom_end=1.0,
                    position_x_start=0.5,
                    position_x_end=0.5,
                    position_y_start=0.5,
                    position_y_end=0.5,
                )
            )

        static_motion_plan = VideoMotionPlan(
            topic=assembly_plan.topic,
            width=assembly_plan.width,
            height=assembly_plan.height,
            fps=assembly_plan.fps,
            instructions=instructions,
            total_duration_seconds=(
                assembly_plan.total_duration_seconds
            ),
        )

        print(
            "Camera motion: DISABLED"
        )

        print(
            "Zoom: DISABLED"
        )

        print(
            "Pan: DISABLED"
        )

        print(
            "Transitions: HARD CUT"
        )

        print()

        # ---------------------------------------------------------
        # Render
        # ---------------------------------------------------------

        renderer = FFmpegVideoRenderer()

        print(
            "Rendering static version..."
        )

        rendered_file = renderer.render(
            assembly_plan=assembly_plan,
            motion_plan=static_motion_plan,
            audio_file=AUDIO_FILE,
            output_file=OUTPUT_FILE,
        )

        # ---------------------------------------------------------
        # Final validation
        # ---------------------------------------------------------

        probe = renderer._probe_media(
            rendered_file
        )

        print()
        print(
            "RITZZ — STATIC RENDER RESULT"
        )
        print(
            "============================="
        )

        print(
            f"Status: COMPLETED"
        )

        print(
            f"Scenes: {len(assembly_plan.clips)}"
        )

        print(
            f"Duration: "
            f"{probe['duration_seconds']:.3f}s"
        )

        print(
            f"Resolution: "
            f"{probe['width']}x"
            f"{probe['height']}"
        )

        print(
            f"FPS: "
            f"{probe['fps']:.2f}"
        )

        print(
            f"File size: "
            f"{rendered_file.stat().st_size:,} bytes"
        )

        print()
        print(
            f"Video: {rendered_file}"
        )

        print()
        print(
            "Static video render completed."
        )

        return 0

    except Exception as exc:
        print()
        print(
            "Static video render failed."
        )

        print(
            f"Error: {exc}"
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )