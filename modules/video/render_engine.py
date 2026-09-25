import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from modules.video.engine import VideoAssemblyEngine
from modules.video.models import VideoAssemblyPlan
from modules.video.motion_engine import VideoMotionEngine
from modules.video.motion_models import VideoMotionPlan
from modules.video.render_models import (
    VideoRenderRequest,
    VideoRenderResult,
)


class FFmpegVideoRenderer:
    """
    Renders the Ritzz video using FFmpeg.

    This renderer:
    - Uses the synchronized video timeline.
    - Applies zoom/pan motion.
    - Uses hard cuts between scenes.
    - Adds narration audio.
    - Supports configurable output resolution and FPS.
    - Validates the final MP4 with ffprobe.
    """

    DEFAULT_CODEC = "libx264"
    DEFAULT_PRESET = "medium"
    DEFAULT_CRF = "18"
    DEFAULT_AUDIO_CODEC = "aac"
    DEFAULT_AUDIO_BITRATE = "192k"

    DURATION_TOLERANCE_SECONDS = 0.25

    def __init__(
        self,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
    ) -> None:
        self.ffmpeg_path = (
            ffmpeg_path
            or os.getenv("RITZZ_FFMPEG_PATH")
            or shutil.which("ffmpeg")
        )

        self.ffprobe_path = (
            ffprobe_path
            or os.getenv("RITZZ_FFPROBE_PATH")
            or shutil.which("ffprobe")
        )

        if not self.ffmpeg_path:
            raise FileNotFoundError(
                "FFmpeg executable was not found. "
                "Install FFmpeg or configure "
                "RITZZ_FFMPEG_PATH."
            )

        if not self.ffprobe_path:
            raise FileNotFoundError(
                "ffprobe executable was not found. "
                "Install FFmpeg or configure "
                "RITZZ_FFPROBE_PATH."
            )

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def create_request(
        self,
        assembly_plan_file: str | Path,
        motion_plan_file: str | Path,
        output_file: str | Path,
        audio_file: str | Path | None = None,
    ) -> VideoRenderRequest:
        """
        Create a typed render request.
        """

        return VideoRenderRequest(
            assembly_plan_file=str(
                assembly_plan_file
            ),
            motion_plan_file=str(
                motion_plan_file
            ),
            output_file=str(
                output_file
            ),
            audio_file=(
                str(audio_file)
                if audio_file is not None
                else None
            ),
        )

    def run(
        self,
        request: VideoRenderRequest,
    ) -> VideoRenderResult:
        """
        Render a video and return a structured result.
        """

        try:
            assembly_plan = (
                VideoAssemblyEngine.load_plan(
                    request.assembly_plan_file
                )
            )

            motion_plan = (
                VideoMotionEngine.load_plan(
                    request.motion_plan_file
                )
            )

            audio_path = (
                Path(request.audio_file)
                if request.audio_file
                else self._get_audio_from_plan(
                    assembly_plan
                )
            )

            output_path = Path(
                request.output_file
            )

            self.render(
                assembly_plan=assembly_plan,
                motion_plan=motion_plan,
                audio_file=audio_path,
                output_file=output_path,
            )

            probe = self._probe_media(
                output_path
            )

            return VideoRenderResult(
                status="completed",
                output_file=str(
                    output_path
                ),
                duration_seconds=probe[
                    "duration_seconds"
                ],
                width=probe[
                    "width"
                ],
                height=probe[
                    "height"
                ],
                fps=probe[
                    "fps"
                ],
                file_size_bytes=(
                    output_path.stat().st_size
                ),
                error_message=None,
            )

        except Exception as exc:
            return VideoRenderResult(
                status="failed",
                output_file=None,
                duration_seconds=0,
                width=0,
                height=0,
                fps=0,
                file_size_bytes=0,
                error_message=str(exc),
            )

    def render(
        self,
        assembly_plan: VideoAssemblyPlan,
        motion_plan: VideoMotionPlan,
        audio_file: str | Path,
        output_file: str | Path,
    ) -> Path:
        """
        Render the synchronized plan to MP4.
        """

        self._validate_plans(
            assembly_plan,
            motion_plan,
        )

        audio_path = Path(
            audio_file
        )

        if not audio_path.exists():
            raise FileNotFoundError(
                f"Audio file not found: {audio_path}"
            )

        if not audio_path.is_file():
            raise ValueError(
                f"Audio path is not a file: {audio_path}"
            )

        if audio_path.stat().st_size <= 0:
            raise ValueError(
                f"Audio file is empty: {audio_path}"
            )

        audio_probe = self._probe_media(
            audio_path
        )

        audio_duration = (
            audio_probe["duration_seconds"]
        )

        if abs(
            audio_duration
            - assembly_plan.total_duration_seconds
        ) > self.DURATION_TOLERANCE_SECONDS:
            raise ValueError(
                "Audio duration does not match "
                "the synchronized video duration. "
                f"Audio={audio_duration:.3f}s, "
                f"Plan={assembly_plan.total_duration_seconds:.3f}s."
            )

        image_paths = [
            Path(clip.image_path)
            for clip in assembly_plan.clips
        ]

        for image_path in image_paths:
            self._validate_image(
                image_path
            )

        output_path = Path(
            output_file
        )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        filter_script = self.build_filter_script(
            assembly_plan,
            motion_plan,
        )

        with tempfile.TemporaryDirectory(
            prefix="ritzz_ffmpeg_"
        ) as temp_directory:

            filter_file = (
                Path(temp_directory)
                / "filter_complex.txt"
            )

            filter_file.write_text(
                filter_script,
                encoding="utf-8",
            )

            # FFmpeg 9 uses the file-input syntax
            # -/filter_complex instead of the removed
            # -filter_complex_script option.
            command = [
                self.ffmpeg_path,
                "-y",
            ]

            for image_path in image_paths:
                command.extend(
                    [
                        "-i",
                        str(image_path),
                    ]
                )

            audio_input_index = len(
                image_paths
            )

            command.extend(
                [
                    "-i",
                    str(audio_path),

                    "-/filter_complex",
                    str(filter_file),

                    "-map",
                    "[vout]",

                    "-map",
                    f"{audio_input_index}:a:0",

                    "-t",
                    f"{assembly_plan.total_duration_seconds:.3f}",

                    "-c:v",
                    self.DEFAULT_CODEC,

                    "-preset",
                    self.DEFAULT_PRESET,

                    "-crf",
                    self.DEFAULT_CRF,

                    "-pix_fmt",
                    "yuv420p",

                    "-c:a",
                    self.DEFAULT_AUDIO_CODEC,

                    "-b:a",
                    self.DEFAULT_AUDIO_BITRATE,

                    "-movflags",
                    "+faststart",

                    str(output_path),
                ]
            )

            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )

            if completed.returncode != 0:
                raise RuntimeError(
                    "FFmpeg rendering failed.\n"
                    f"Command: {' '.join(command)}\n"
                    f"STDOUT:\n{completed.stdout}\n"
                    f"STDERR:\n{completed.stderr}"
                )

        if not output_path.exists():
            raise RuntimeError(
                "FFmpeg completed but the output "
                f"file was not created: {output_path}"
            )

        if output_path.stat().st_size <= 0:
            raise RuntimeError(
                "FFmpeg created an empty output file: "
                f"{output_path}"
            )

        self._validate_rendered_output(
            output_path,
            assembly_plan,
        )

        return output_path

    # -----------------------------------------------------------------
    # Filter generation
    # -----------------------------------------------------------------

    def build_filter_script(
        self,
        assembly_plan: VideoAssemblyPlan,
        motion_plan: VideoMotionPlan,
    ) -> str:
        """
        Build the FFmpeg filter graph.

        Every scene is rendered independently and then
        concatenated using normal hard cuts.
        """

        self._validate_plans(
            assembly_plan,
            motion_plan,
        )

        filters: list[str] = []

        video_labels: list[str] = []

        for index, (
            clip,
            instruction,
        ) in enumerate(
            zip(
                assembly_plan.clips,
                motion_plan.instructions,
            )
        ):
            input_label = (
                f"[{index}:v]"
            )

            output_label = (
                f"[v{index}]"
            )

            video_labels.append(
                output_label
            )

            frames = max(
                1,
                int(
                    round(
                        clip.duration_seconds
                        * assembly_plan.fps
                    )
                ),
            )

            denominator = max(
                frames - 1,
                1,
            )

            zoom_expression = (
                f"{instruction.zoom_start:.6f}"
                f"+("
                f"{instruction.zoom_end:.6f}"
                f"-"
                f"{instruction.zoom_start:.6f}"
                f")*on/{denominator}"
            )

            x_expression = (
                f"(iw-iw/zoom)*("
                f"{instruction.position_x_start:.6f}"
                f"+("
                f"{instruction.position_x_end:.6f}"
                f"-"
                f"{instruction.position_x_start:.6f}"
                f")*on/{denominator}"
                f")"
            )

            y_expression = (
                f"(ih-ih/zoom)*("
                f"{instruction.position_y_start:.6f}"
                f"+("
                f"{instruction.position_y_end:.6f}"
                f"-"
                f"{instruction.position_y_start:.6f}"
                f")*on/{denominator}"
                f")"
            )

            duration = (
                f"{clip.duration_seconds:.6f}"
            )

            if instruction.motion == "static":
                filter_expression = (
                    f"{input_label}"
                    f"loop=loop=-1:size=1:start=0,"
                    f"scale="
                    f"{assembly_plan.width}:"
                    f"{assembly_plan.height}:"
                    f"force_original_aspect_ratio=decrease,"
                    f"pad="
                    f"{assembly_plan.width}:"
                    f"{assembly_plan.height}:"
                    f"(ow-iw)/2:"
                    f"(oh-ih)/2,"
                    f"setsar=1,"
                    f"fps={assembly_plan.fps},"
                    f"trim=duration={duration},"
                    f"setpts=PTS-STARTPTS"
                    f"{output_label}"
                )
                filters.append(filter_expression)
                continue

            filter_expression = (
                f"{input_label}"
                f"scale="
                f"{assembly_plan.width}:"
                f"{assembly_plan.height}:"
                f"force_original_aspect_ratio=decrease,"
                f"pad="
                f"{assembly_plan.width}:"
                f"{assembly_plan.height}:"
                f"(ow-iw)/2:"
                f"(oh-ih)/2,"
                f"setsar=1,"
                f"zoompan="
                f"z='{zoom_expression}':"
                f"x='{x_expression}':"
                f"y='{y_expression}':"
                f"d={frames}:"
                f"s="
                f"{assembly_plan.width}x"
                f"{assembly_plan.height}:"
                f"fps={assembly_plan.fps},"
                f"trim="
                f"duration={duration},"
                f"setpts=PTS-STARTPTS"
                f"{output_label}"
            )

            filters.append(
                filter_expression
            )

        concat_inputs = "".join(
            video_labels
        )

        filters.append(
            f"{concat_inputs}"
            f"concat="
            f"n={len(video_labels)}:"
            f"v=1:"
            f"a=0"
            f"[vconcat]"
        )

        filters.append(
            "[vconcat]"
            "format=yuv420p"
            "[vout]"
        )

        return ";\n".join(
            filters
        ) + ";\n"

    # -----------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------

    @staticmethod
    def _validate_plans(
        assembly_plan: VideoAssemblyPlan,
        motion_plan: VideoMotionPlan,
    ) -> None:
        """
        Validate that the assembly and motion plans
        represent exactly the same timeline.
        """

        if assembly_plan.topic != motion_plan.topic:
            raise ValueError(
                "Assembly plan topic does not match "
                "motion plan topic."
            )

        if len(
            assembly_plan.clips
        ) != len(
            motion_plan.instructions
        ):
            raise ValueError(
                "Assembly clip count does not match "
                "motion instruction count."
            )

        if (
            assembly_plan.width
            != motion_plan.width
        ):
            raise ValueError(
                "Assembly width does not match "
                "motion plan width."
            )

        if (
            assembly_plan.height
            != motion_plan.height
        ):
            raise ValueError(
                "Assembly height does not match "
                "motion plan height."
            )

        if (
            assembly_plan.fps
            != motion_plan.fps
        ):
            raise ValueError(
                "Assembly FPS does not match "
                "motion plan FPS."
            )

        if abs(
            assembly_plan.total_duration_seconds
            - motion_plan.total_duration_seconds
        ) > 0.01:
            raise ValueError(
                "Assembly duration does not match "
                "motion plan duration."
            )

        for index, (
            clip,
            instruction,
        ) in enumerate(
            zip(
                assembly_plan.clips,
                motion_plan.instructions,
            )
        ):
            if (
                clip.scene_id
                != instruction.scene_id
            ):
                raise ValueError(
                    "Scene ordering mismatch "
                    f"at index {index}."
                )

            if abs(
                clip.start_seconds
                - instruction.start_seconds
            ) > 0.01:
                raise ValueError(
                    f"{clip.scene_id} start time does not "
                    "match motion plan."
                )

            if abs(
                clip.duration_seconds
                - instruction.duration_seconds
            ) > 0.01:
                raise ValueError(
                    f"{clip.scene_id} duration does not "
                    "match motion plan."
                )

    @staticmethod
    def _validate_image(
        image_path: Path,
    ) -> None:
        """
        Validate that an image exists and is non-empty.
        """

        if not image_path.exists():
            raise FileNotFoundError(
                f"Image file not found: {image_path}"
            )

        if not image_path.is_file():
            raise ValueError(
                f"Image path is not a file: {image_path}"
            )

        if image_path.stat().st_size <= 0:
            raise ValueError(
                f"Image file is empty: {image_path}"
            )

    @staticmethod
    def _get_audio_from_plan(
        assembly_plan: VideoAssemblyPlan,
    ) -> Path:
        """
        Get the audio file configured in the assembly plan.
        """

        if not assembly_plan.audio_path:
            raise ValueError(
                "No audio file was supplied and the "
                "assembly plan does not contain an audio path."
            )

        return Path(
            assembly_plan.audio_path
        )

    # -----------------------------------------------------------------
    # FFprobe
    # -----------------------------------------------------------------

    def _probe_media(
        self,
        media_file: str | Path,
    ) -> dict[str, Any]:
        """
        Probe a media file using ffprobe.
        """

        path = Path(
            media_file
        )

        command = [
            self.ffprobe_path,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

        if completed.returncode != 0:
            raise RuntimeError(
                "ffprobe failed for "
                f"{path}.\n{completed.stderr}"
            )

        try:
            data = json.loads(
                completed.stdout
            )
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "ffprobe returned invalid JSON."
            ) from exc

        streams = data.get(
            "streams",
            [],
        )

        format_data = data.get(
            "format",
            {},
        )

        duration = float(
            format_data.get(
                "duration",
                0,
            )
        )

        video_stream = next(
            (
                stream
                for stream in streams
                if stream.get("codec_type")
                == "video"
            ),
            None,
        )

        audio_stream = next(
            (
                stream
                for stream in streams
                if stream.get("codec_type")
                == "audio"
            ),
            None,
        )

        width = int(
            video_stream.get(
                "width",
                0,
            )
        ) if video_stream else 0

        height = int(
            video_stream.get(
                "height",
                0,
            )
        ) if video_stream else 0

        fps = 0.0

        if video_stream:
            fps_text = video_stream.get(
                "r_frame_rate",
                "0/1",
            )

            try:
                numerator, denominator = (
                    fps_text.split("/")
                )

                fps = (
                    float(numerator)
                    / float(denominator)
                )
            except (
                ValueError,
                ZeroDivisionError,
            ):
                fps = 0.0

        return {
            "duration_seconds": duration,
            "width": width,
            "height": height,
            "fps": fps,
            "has_video": (
                video_stream is not None
            ),
            "has_audio": (
                audio_stream is not None
            ),
        }

    def _validate_rendered_output(
        self,
        output_file: Path,
        assembly_plan: VideoAssemblyPlan,
    ) -> None:
        """
        Validate the completed MP4.
        """

        probe = self._probe_media(
            output_file
        )

        if not probe["has_video"]:
            raise ValueError(
                "Rendered output does not contain "
                "a video stream."
            )

        if not probe["has_audio"]:
            raise ValueError(
                "Rendered output does not contain "
                "an audio stream."
            )

        if probe["width"] != (
            assembly_plan.width
        ):
            raise ValueError(
                "Rendered video width does not match "
                "assembly plan."
            )

        if probe["height"] != (
            assembly_plan.height
        ):
            raise ValueError(
                "Rendered video height does not match "
                "assembly plan."
            )

        if abs(
            probe["fps"]
            - assembly_plan.fps
        ) > 0.1:
            raise ValueError(
                "Rendered video FPS does not match "
                "assembly plan."
            )

        if abs(
            probe["duration_seconds"]
            - assembly_plan.total_duration_seconds
        ) > self.DURATION_TOLERANCE_SECONDS:
            raise ValueError(
                "Rendered video duration does not match "
                "assembly plan."
            )
