"""Render and technically validate the approved test project."""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.image.image_overlays import create_thumbnail
from modules.project.manager import ProjectManager
from modules.project.packaging import PackagingArtifact
from modules.storyboard.engine import StoryboardEngine
from modules.video.pipeline_engine import VideoProductionPipeline


def _validate_production_render_format(probe: dict[str, object]) -> None:
    width = probe.get("width")
    height = probe.get("height")
    fps = probe.get("fps")
    if (
        not isinstance(width, int)
        or not isinstance(height, int)
        or width != 1920
        or height != 1080
        or width * 9 != height * 16
    ):
        raise RuntimeError(
            "Production render must be exactly 1920x1080 with a 16:9 aspect ratio; "
            f"received {width}x{height}."
        )
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or fps != 30.0:
        raise RuntimeError(f"Production render must be exactly 30 FPS; received {fps}.")
    codec = probe.get("video_codec_name")
    if codec is not None and codec != "h264":
        raise RuntimeError(f"Production render must use H.264; received {codec}.")
    bitrate = probe.get("video_bit_rate_bps")
    if isinstance(bitrate, (int, float)) and bitrate < 1_200_000:
        raise RuntimeError(f"Production render bitrate is below the configured minimum: {bitrate}.")


def _reject_semantic_qa_fail(status: str) -> None:
    if status == "FAIL":
        raise RuntimeError(
            "Rendered-video semantic QA found a clear scene/narration mismatch."
        )


def _reuse_or_create_thumbnail(
    thumbnail_file: str | Path,
    source_image: str | Path,
    title: str,
    *,
    probe_media: Callable[[str | Path], dict[str, object]] | None = None,
) -> Path:
    thumbnail = Path(thumbnail_file)
    if thumbnail.is_file():
        if probe_media is None:
            ffprobe = shutil.which("ffprobe")
            if not ffprobe:
                raise FileNotFoundError("FFprobe is required to validate an existing thumbnail.")
            result = subprocess.run(
                [
                    ffprobe, "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=width,height",
                    "-of", "json", str(thumbnail),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            import json

            streams = json.loads(result.stdout).get("streams", [])
            dimensions = streams[0] if streams else {}
            probe = {"width": dimensions.get("width"), "height": dimensions.get("height")}
        else:
            probe = probe_media(thumbnail)
        if probe.get("width") != 1280 or probe.get("height") != 720:
            raise RuntimeError("Existing thumbnail must remain 1280x720.")
        return thumbnail
    return create_thumbnail(source_image, thumbnail, title)


def main() -> int:
    project_id = os.environ["RITZZ_PROJECT_ID"]
    project_manager = ProjectManager(Path("projects"))
    project = project_manager.load_project(project_id)
    project_directory = project_manager.get_project_path(project)
    storyboard_file = project_directory / "storyboard" / "storyboard_audio_timed.json"
    image_directory = project_directory / "images"
    narration_result_file = project_directory / "voice" / "narration_result.json"
    audio_file = project_directory / "voice" / "narration.mp3"
    output_directory = project_directory / "video"
    output_video_file = output_directory / "ritzz_test.mp4"

    pipeline = VideoProductionPipeline()
    request = pipeline.create_request(
        storyboard_file=storyboard_file,
        image_directory=image_directory,
        narration_result_file=narration_result_file,
        audio_file=audio_file,
        output_directory=output_directory,
        output_video_file=output_video_file,
        resume=True,
        enable_image_ai_qa=True,
    )
    result = pipeline.run(request)
    print(f"Render status: {result.status}")
    print(f"Technical QA: {result.technical_qa_status}")
    print(f"Output: {result.output_video_file}")
    if result.status != "completed" or result.technical_qa_status != "PASS":
        raise RuntimeError(result.error_message or "Render or technical QA failed.")

    storyboard = StoryboardEngine.load_storyboard(storyboard_file)
    packaging_file = project_directory / "packaging.json"
    artifact = PackagingArtifact.from_dict(
        json.loads(packaging_file.read_text(encoding="utf-8"))
    )
    thumbnail_file = output_directory / "thumbnail.jpg"
    _reuse_or_create_thumbnail(
        thumbnail_file,
        image_directory / f"{storyboard.scenes[0].scene_id}.png",
        artifact.selected_title,
        probe_media=pipeline.renderer._probe_media,
    )
    if not thumbnail_file.is_file() or thumbnail_file.stat().st_size == 0:
        raise RuntimeError(
            f"Thumbnail generation did not produce a valid file: {thumbnail_file}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
