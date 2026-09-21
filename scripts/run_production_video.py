import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.video.pipeline_engine import (
    VideoProductionPipeline,
)


PROJECT_ID = (
    "20260820_001_why_do_pirates_wear_eye_patches"
)

PROJECT_DIRECTORY = (
    PROJECT_ROOT / "projects" / PROJECT_ID
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

NARRATION_RESULT_FILE = (
    PROJECT_DIRECTORY
    / "voice"
    / "narration_result.json"
)

AUDIO_FILE = (
    PROJECT_DIRECTORY
    / "voice"
    / "narration.mp3"
)

OUTPUT_DIRECTORY = (
    PROJECT_DIRECTORY
    / "video"
)

OUTPUT_VIDEO_FILE = (
    OUTPUT_DIRECTORY
    / "pirates_eye_patch_final.mp4"
)


def main() -> int:
    print()
    print(
        "RITZZ — FULL PRODUCTION VIDEO"
    )
    print(
        "=============================="
    )
    print(
        f"Storyboard: {STORYBOARD_FILE}"
    )
    print(
        f"Images:    {IMAGE_DIRECTORY}"
    )
    print(
        f"Audio:     {AUDIO_FILE}"
    )
    print(
        f"Alignment: {NARRATION_RESULT_FILE}"
    )
    print(
        f"Output:    {OUTPUT_VIDEO_FILE}"
    )
    print()

    if not STORYBOARD_FILE.exists():
        raise FileNotFoundError(
            f"Storyboard not found: {STORYBOARD_FILE}"
        )

    if not NARRATION_RESULT_FILE.exists():
        raise FileNotFoundError(
            "Narration result not found: "
            f"{NARRATION_RESULT_FILE}"
        )

    if not AUDIO_FILE.exists():
        raise FileNotFoundError(
            f"Audio file not found: {AUDIO_FILE}"
        )

    image_count = len(
        list(
            IMAGE_DIRECTORY.glob("*.png")
        )
    )

    print(
        f"Production images found: {image_count}"
    )

    if image_count != 96:
        raise ValueError(
            f"Expected 96 production images, "
            f"found {image_count}."
        )

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    pipeline = VideoProductionPipeline()

    request = pipeline.create_request(
        storyboard_file=STORYBOARD_FILE,
        image_directory=IMAGE_DIRECTORY,
        narration_result_file=(
            NARRATION_RESULT_FILE
        ),
        audio_file=AUDIO_FILE,
        output_directory=OUTPUT_DIRECTORY,
        output_video_file=OUTPUT_VIDEO_FILE,
    )

    print()
    print(
        "Starting full video production..."
    )
    print()

    result = pipeline.run(
        request
    )

    print()
    print(
        "RITZZ — PRODUCTION RESULT"
    )
    print(
        "=========================="
    )
    print(
        f"Status:    {result.status}"
    )
    print(
        f"Scenes:    {result.scene_count}"
    )
    print(
        f"Duration:  "
        f"{result.duration_seconds:.3f}s"
    )
    print(
        f"Video:     {result.output_video_file}"
    )

    if result.status != "completed":
        print()
        print(
            f"Error: {result.error_message}"
        )
        return 1

    print()
    print(
        "FULL PRODUCTION VIDEO COMPLETED."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )